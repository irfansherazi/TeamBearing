"""
vQA — Structured AC Parser Node
==================================
Module: backend/engine/ac_parser.py

Implements the **two-stage structured AC parser** that replaces the
free-form inline ``ac_parser_node`` in ``graph.py``.

Pipeline
--------
::

    Jira AC text
        │
        ▼
    Stage 1: BDD Normalizer  (LLM)
        │   Converts messy Jira text → clean Given/When/Then
        │   Expands implicit preconditions (login, navigation)
        ▼
    Stage 2: JSON Compiler  (LLM + Pydantic validation)
        │   Compiles BDD → strict TestPlan JSON
        │   Maps UI terms → PrimeNG component identifiers
        │   Generates programmatic verification assertions
        ▼
    Dual-Write Output
        ├─► test_plan (structured, new)
        └─► acceptance_criteria_steps (legacy string list)

Backward Compatibility
----------------------
The new parser populates BOTH:
  - ``test_plan``: the full ``TestPlan`` dict with typed steps,
    preconditions, target components, and assertions.
  - ``acceptance_criteria_steps``: ``[step.goal for step in plan.steps]``
    — a plain string list for the 13+ downstream consumers that still
    read this field.

This dual-write strategy ensures zero breakage while allowing consumers
to progressively adopt the structured plan data.

Dependencies
------------
  - ``langchain-aws``                — ChatBedrockConverse for Claude
  - ``backend/engine/schemas.py``    — TestPlan Pydantic model
  - ``backend/engine/prompts.py``    — Stage 1 & 2 system prompts
  - ``backend/engine/validators.py`` — AC step quality validation
  - ``backend/config.py``            — Bedrock model ID and region

See Also
--------
  - ``backend/engine/graph.py``  — registers this node in the StateGraph
  - ``backend/engine/state.py``  — VQAState with test_plan field
"""

import asyncio
import json
import logging
import re
import time

import boto3
import instructor
from langchain_aws import ChatBedrockConverse  # kept for type hints (Stage 1)
from langchain_core.messages import HumanMessage, SystemMessage

from backend.config import settings
from backend.engine import ac_parse_cache as _content_cache  # T2-a: persistent disk cache
from backend.engine.ac_parse_drift import ACParseDriftError, ACParseDriftGuard  # T3-d
from backend.engine.ac_enricher import enrich_ac_text
from backend.engine.ac_quality_gate import score_ac_quality, split_ac_into_steps
from backend.engine.metrics import get_run_metrics
from backend.engine.prompts import BDD_NORMALIZER_PROMPT, JSON_COMPILER_PROMPT
from backend.engine.schemas import TestPlan, Verification
from backend.engine.state import VQAState
from backend.engine.validators import validate_ac_steps
from backend.engine.vision_analyzer import VisionAnalyzer
from backend.jira.client import download_attachment
from backend.kb.preflight import build_global_context

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FAIR Guardrail (TASK-096 / FEAT-077)
# ---------------------------------------------------------------------------
# Per-run asyncio.Event objects used to block ac_parser_node when a FAIR-grade
# ticket is detected and the operator has not yet provided guidance or approval.
#
# Lifecycle:
#   1. ac_parser_node creates and stores the event (cleared = blocking).
#   2. _broadcast_pre_parse_guidance_required() sends a WS message to the frontend.
#   3. Frontend shows the Pre-Parse Guidance panel.
#   4. Operator submits guidance or clicks "Proceed Anyway".
#   5. POST /run/{run_id}/resume sets the event, unblocking ac_parser_node.
#   6. ac_parser_node reads guidance from _resume_data and proceeds.
#
# The event is removed from the dict once the node unblocks (cleanup below).
_pre_parse_events: dict[str, asyncio.Event] = {}


async def _broadcast_pre_parse_guidance_required(
    run_id: str,
    warnings: list[str],
    quality_grade: str,
    overall_score: int,
) -> None:
    """
    Broadcast a ``pre_parse_guidance_required`` WebSocket event.

    Sends a ``WSPreParseGuidanceMessage`` to all WebSocket clients connected
    to ``run_id``.  Called by ``ac_parser_node`` immediately before blocking
    on the ``_pre_parse_events`` asyncio.Event.

    The frontend should render the Pre-Parse Guidance panel (modal/sidebar)
    listing the FAIR-grade deficiencies and providing a text area for the
    operator to supply additional context.

    Args
    ----
    run_id : str
        The run identifier.
    warnings : list[str]
        Quality deficiency descriptions from ``score_ac_quality()``.
    quality_grade : str
        Always ``"fair"`` when this is called.
    overall_score : int
        0–10 composite quality score from ``ACQualityResult``.
    """
    # Import here to avoid circular imports (ac_parser ← routes ← ac_parser)
    try:
        from backend.api.routes import _ws_connections  # noqa: PLC0415
        from backend.api.schemas import WSPreParseGuidanceMessage  # noqa: PLC0415
    except ImportError:
        logger.warning(
            "[%s] _broadcast_pre_parse_guidance_required: could not import routes (test mode?)",
            run_id,
        )
        return

    connections = _ws_connections.get(run_id, [])
    if not connections:
        logger.debug(
            "[%s] _broadcast_pre_parse_guidance_required: no WS connections — skipping broadcast",
            run_id,
        )
        return

    msg = WSPreParseGuidanceMessage(
        run_id=run_id,
        warnings=warnings,
        quality_grade=quality_grade,
        overall_score=overall_score,
    )
    msg_json = msg.model_dump_json()

    disconnected = []
    for ws in connections:
        try:
            await ws.send_text(msg_json)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connections.remove(ws)

    logger.info(
        "[%s] FAIR guardrail: broadcast pre_parse_guidance_required (score=%d, %d warnings)",
        run_id,
        overall_score,
        len(warnings),
    )



_PRODUCT_STACK_HINTS: dict[str, str] = {
    "vpromotions": (
        "vPromotions is served via a TWO-PHASE app boundary. Widget stack\n"
        "depends on which host the browser is on RIGHT NOW:\n"
        "\n"
        "PHASE 1 — SSO auth + product picker (host: two-test.vcreative.net,\n"
        "vcreative.net; URLs contain /#/login, /#/select-product):\n"
        "  This IS an Angular + PrimeNG app (the shared vSuite SSO shell).\n"
        "  Auth writes localStorage 'vc2JWT'.\n"
        "  During PHASE 1 you MAY reference PrimeNG components:\n"
        "    - p-inputtext / p-password  (email + password fields)\n"
        "    - p-button                  (LOGIN button, product tiles)\n"
        "    - get_by_role('button', name='Log In'|'LOGIN')\n"
        "  Steps that live in PHASE 1:\n"
        "    - Sign in / log in / enter email / enter password / click LOGIN\n"
        "    - Click the 'vPromotions' product tile on /#/select-product\n"
        "\n"
        "PHASE 2 — inside vPromotions proper (host: vpromotions-rc.vcreative.net,\n"
        "URL path /app_test.php/promo or /promo). THIS is the legacy stack:\n"
        "  - Symfony 2 + jQuery 2.1 + Bootstrap 3 (NOT Angular, NOT PrimeNG).\n"
        "  - Dropdowns:      select2 3.x (jQuery plugin)   NOT p-dropdown\n"
        "  - Multi-selects:  select2 select2tags variant   NOT p-multiselect\n"
        "  - Date/time:      jQuery UI datetimepicker      NOT p-calendar\n"
        "  - Radio/checkbox: native <input type=…>         NOT p-radiobutton / p-checkbox\n"
        "  - File upload:    Dropzone.js                   NOT p-fileupload / native <input type=file>\n"
        "  - Modals:         Bootstrap 3 .modal            NOT p-dialog / p-confirmdialog\n"
        "  - Rich text:      contenteditable <span class='tasp'>\n"
        "                    (wysihtml5 is only used for Liners flow, not the PRF drawer)\n"
        "  - Toasts:         toastr                        NOT p-toast\n"
        "  - Post-auth token: session cookie 'ssojwt' at .vcreative.net (NOT vc2JWT)\n"
        "\n"
        "STEP-WRITING RULES:\n"
        "  ✓ For auth / product-picker steps, PrimeNG references are ALLOWED.\n"
        "  ✓ For every step that happens INSIDE vPromotions, use generic language:\n"
        "    'Pick a category', 'Fill the description', 'Upload a file', 'Save the PRF'.\n"
        "  ✗ Do NOT emit p-multiselect / p-fileupload / p-calendar / p-dropdown for\n"
        "    PHASE 2 steps. The vPromotions app has no PrimeNG components.\n"
        "  ✗ Never split a single logical action into an 'Angular change-detection\n"
        "    wait' followed by an action — vPromotions is jQuery, no change detection.\n"
        "\n"
        "KNOWN NAVIGATION FLOW (append implicit auth substeps if the ticket assumes\n"
        "the user is already logged in — do NOT skip them):\n"
        "  1. Load vpromotions-rc.vcreative.net/app_test.php/promo\n"
        "  2. → 302 to two-test.vcreative.net/#/login  (PHASE 1)\n"
        "  3. Fill email, fill password, click LOGIN    (PHASE 1)\n"
        "  4. → two-test.vcreative.net/#/select-product (PHASE 1)\n"
        "  5. Click 'vPromotions' tile                  (PHASE 1)\n"
        "  6. → vpromotions-rc.vcreative.net/…/promo    (PHASE 2 starts here)\n"
        "  7. Home tab renders after a 1000ms setTimeout — the PRF calendar and\n"
        "     the New PRF button (#create_new_prf) appear only after this settle.\n"
        "  8. PRF form is a right-side DRAWER at #prf_form_rightview, not a modal.\n"
        "\n"
        "url_pattern CONVENTIONS FOR NAVIGATE steps (do NOT reverse these):\n"
        "  ✓ 'Navigate to login page'      → url_pattern: '/#/login'\n"
        "  ✓ 'Navigate to product picker'  → url_pattern: '/select-product'\n"
        "  ✓ 'Navigate to vPromotions app' → url_pattern: 'vpromotions-rc' (or '/app_test.php/promo' or '/promo')\n"
        "  ✓ 'Navigate to PRF home page'   → url_pattern: 'vpromotions-rc' (or '/app_test.php/promo' or '/promo')\n"
        "  ✗ NEVER emit url_pattern='/#/login' for a step whose goal is to REACH vPromotions.\n"
        "    url_pattern names the URL you EXPECT AFTER the action, not before it.\n"
    ),
}


# When Stage 2 emits url_pattern for a NAVIGATE-type verify check on a vpromotions
# ticket, these substrings indicate the LLM got the direction backwards (used a
# Phase 1 auth URL as the "expected destination" for a step whose goal is Phase 2).
# The verifier uses this list to permit navigation completion when the browser is
# clearly past the auth stage and on the product's own host.
_VPROMOTIONS_PHASE2_HOSTS = ("vpromotions-rc.vcreative.net", "/app_test.php/promo", "/promo",)
_VPROMOTIONS_PHASE1_MARKERS = ("/#/login", "/#/select-product", "two-test.vcreative.net/#/",)


def _looks_like_phase2_url(url: str) -> bool:
    if not url:
        return False
    lower = url.lower()
    on_phase1 = any(m in lower for m in _VPROMOTIONS_PHASE1_MARKERS)
    on_phase2_host = any(h in lower for h in _VPROMOTIONS_PHASE2_HOSTS)
    return on_phase2_host and not on_phase1


def _get_product_stack_hint(product: str | None) -> str:
    """Return the widget-stack hint block for `product`, or empty string."""
    if not product:
        return ""
    return _PRODUCT_STACK_HINTS.get(product.lower(), "")


def _get_parser_llm(max_tokens: int = 2048) -> ChatBedrockConverse:
    """
    Create an LLM client for the AC parser.

    Uses the centralized ``get_llm()`` factory from ``backend.llm``.
    Temperature=0 for deterministic, reproducible parsing.
    Higher max_tokens than the planner because test plans can be
    larger than single-action responses.
    """
    from backend.llm import get_llm

    return get_llm("parser", max_tokens=max_tokens)


def _repair_json(raw: str) -> str:
    """
    Attempt to repair truncated or malformed JSON from LLM output.

    Strategy:
    1. Strip markdown fences
    2. Remove trailing commas before } or ]
    3. If json.loads works → return immediately
    4. Otherwise, iteratively strip characters from the right until
       the remaining prefix + auto-closed brackets is valid JSON
    5. As a final fallback, return the cleaned-up text with brackets closed

    This handles max_tokens truncation (mid-string, mid-object, mid-array)
    reliably without brittle quote-counting heuristics.
    """
    text = raw.strip()

    # 1. Strip markdown code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # 2. Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # 3. Quick check — maybe it's already valid after fence/comma cleanup
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # 4. Iterative right-trim: strip from right, close brackets, try parse
    # This is brute-force but reliable for LLM truncation patterns.
    # We limit to 500 iterations to avoid pathological cases.
    for trim in range(1, min(len(text), 500)):
        candidate = text[:-trim].rstrip()

        # Strip any trailing partial key (e.g., "goa) or dangling comma/colon
        candidate = re.sub(r"[,:]\s*$", "", candidate)
        candidate = re.sub(r'"[^"]*$', "", candidate)  # remove unterminated string
        candidate = re.sub(r"[,:]\s*$", "", candidate)  # clean again after string removal

        # Count and close brackets
        open_braces = candidate.count("{") - candidate.count("}")
        open_brackets = candidate.count("[") - candidate.count("]")

        if open_braces < 0 or open_brackets < 0:
            continue  # over-closed, keep trimming

        closers = "]" * open_brackets + "}" * open_braces
        attempt = candidate + closers

        try:
            json.loads(attempt)
            return attempt
        except json.JSONDecodeError:
            continue

    # 5. Last resort: close brackets on the original cleaned text
    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")
    closers = "]" * max(0, open_brackets) + "}" * max(0, open_braces)
    return text + closers


def _detect_step_ambiguity(bdd_text: str) -> list[str]:
    """
    FEAT-058: Detect vague or untestable goals in the BDD text.

    Heuristics:
    1. Vague sort: 'sorts correctly' without column/direction.
    2. Missing subject: 'click the button' without name/selector.
    3. Generic verification: 'verify it works' or 'verify the page'.

    Returns
    -------
    list[str]
        List of detected ambiguity warnings.
    """
    warnings = []
    lines = [line.strip().lower() for line in bdd_text.split("\n") if line.strip()]

    VAGUE_ADVERBS = ["correctly", "properly", "successfully", "as expected", "works", "valid"]

    for line in lines:
        # 1. Vague Sort Check
        if "sort" in line:
            has_direction = "ascen" in line or "descen" in line or "a-z" in line or "z-a" in line
            if not has_direction:
                if any(adv in line for adv in VAGUE_ADVERBS):
                    warnings.append(f"Vague Sort Goal: '{line}' needs a specific direction (e.g., 'ascending').")

        # 2. Missing Subject Check
        if line.startswith("when click"):
            # If it's just "click the button" or "click on it"
            if re.search(r"click (the |a )?(button|link|element|item)$", line) or "click it" in line:
                warnings.append(f"Missing Subject: '{line}' does not specify which element to click.")

        # 3. Generic Verification Check
        if line.startswith("then verify"):
            if any(phrase in line for phrase in ["it works", "the page", "everything is correct"]):
                warnings.append(f"Generic Verification: '{line}' is too broad to be grounded into a specific check.")

    return warnings


# Compiled once at module load for performance.
# First segment: a single word (no spaces) — app/menu root name like "HDah".
# Subsequent segments: word(s) separated by spaces — e.g. "Module Abilities".
# This prevents greedy capture of surrounding prose (e.g. "Given the user navigates to").
_NAV_PATH_RE = re.compile(
    r'\b([A-Za-z][A-Za-z0-9]{0,49}(?:\s*>\s*[A-Za-z][A-Za-z0-9 ]{0,49})+)'
)


def _detect_nav_paths(raw_ac: str) -> list[str]:
    """
    TASK-122: Detect navigation paths using '>' delimiter notation in raw AC text.

    Scans the raw Acceptance Criteria text for sequences like
    'HDah > Module Abilities > Edit Module' before Stage 1 normalization.
    Raw text is used (not post-Stage-1 BDD) because PMs write the '>' notation
    as a structural shorthand that Stage 1 may paraphrase into prose.

    Returns
    -------
    list[str]
        Deduplicated list of detected navigation paths, preserving first-seen order.
        Returns empty list when no paths are found.
    """
    if not raw_ac:
        return []
    matches = _NAV_PATH_RE.findall(raw_ac)
    cleaned = [m.strip() for m in matches]
    return list(dict.fromkeys(cleaned))


# ---------------------------------------------------------------------------
# Stage 1 — BDD Normalizer
# ---------------------------------------------------------------------------


async def _stage_1_normalize(
    raw_ac: str,
    summary: str,
    description: str,
    run_id: str,
    visual_context: str = "",
    pre_parse_guidance: str = "",
    critic_feedback: dict | None = None,
    product: str | None = None,
) -> str:
    """
    Stage 1: Normalize raw Jira AC text into BDD Given/When/Then format.

    The BDD normalizer expands implicit preconditions, converts vague
    requirements into testable statements, and structures the text
    for Stage 2 compilation.

    Args
    ----
    raw_ac : str
        Raw Acceptance Criteria text from Jira.
    summary : str
        Jira ticket summary/title.
    description : str
        Full Jira ticket description (additional context).
    run_id : str
        Run identifier for logging.
    visual_context : str
        Visual facts extracted from Jira attachments via Vision LLM.
    pre_parse_guidance : str
        Optional human guidance.
    critic_feedback : dict | None
        Structured feedback from critic_node on a retry pass.
        When non-None, a HumanMessage is appended to the conversation
        carrying the critic's reason_codes and guidance so the normalizer
        can address the detected AC-vs-TestPlan mismatch.
        Shape: {"reason_codes": list[str], "guidance": str}.
        The BDD_NORMALIZER_PROMPT system prompt stays byte-identical to
        preserve Bedrock's implicit prompt cache (creative Q2 — Option B).

    Returns
    -------
    str
        Clean BDD scenario text (Given/When/Then).
    """
    llm = _get_parser_llm(max_tokens=2048)

    system_prompt = BDD_NORMALIZER_PROMPT.format(
        ticket_summary=summary,
        acceptance_criteria=raw_ac,
        visual_context=visual_context or "(no visual context available)",
        ticket_description=description or "(no description provided)",
    )

    # Append human pre-parse guidance if provided (before Bedrock call)
    if pre_parse_guidance and pre_parse_guidance.strip():
        system_prompt += (
            "\n\n══════════════════════════════════════════════════════════════\n"
            "HUMAN CONTEXT (provided by the QA team before AC generation):\n"
            "Use this context to write more accurate, specific AC steps.\n"
            "══════════════════════════════════════════════════════════════\n"
            f"{pre_parse_guidance.strip()}\n"
            "══════════════════════════════════════════════════════════════\n"
        )

    # Product-specific widget-stack guidance. Prevents Stage 1 from
    # generating PrimeNG-shaped steps (p-multiselect, p-fileupload,
    # p-dropdown, p-calendar, p-radiobutton) for products that don't use
    # PrimeNG. vpromotions is legacy jQuery — its AC steps must NOT reference
    # PrimeNG component tags or Angular-specific widget names.
    product_stack_hint = _get_product_stack_hint(product)
    if product_stack_hint:
        system_prompt += (
            "\n\n"
            "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓\n"
            f"⚠ AUTHORITATIVE PRODUCT CONSTRAINT — OVERRIDES EARLIER GUIDANCE ⚠\n"
            f"Active product: {product}\n"
            "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓\n"
            "The system prompt above may reference 'vSuite', 'PrimeNG', or\n"
            "Angular components. FOR THIS TICKET, that guidance IS INVALID.\n"
            "Follow the widget-stack constraints below verbatim. If they\n"
            "conflict with anything earlier in this prompt, THE BELOW WINS.\n"
            "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓\n"
            f"{product_stack_hint}"
            "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓\n"
        )

    messages: list = [SystemMessage(content=system_prompt)]

    # critic-pass-llm-evaluator (Phase 2): inject critic feedback as a 2nd turn.
    # The system prompt is byte-identical so Bedrock's implicit prompt cache is
    # preserved on retries (creative Q2 — Option B).
    if critic_feedback:
        reason_codes = critic_feedback.get("reason_codes") or []
        guidance = critic_feedback.get("guidance") or ""
        critic_turn = (
            "CRITIC FEEDBACK (from the pre-execution LLM critic — address these issues):\n"
            f"Detected issue codes: {', '.join(reason_codes) if reason_codes else '(none)'}\n"
            f"\n{guidance}\n"
            "\nRevise the BDD normalisation to correct the detected mismatch(es)."
        )
        messages.append(HumanMessage(content=critic_turn))
        logger.info(
            "[%s] _stage_1_normalize: injecting critic_feedback (reason_codes=%s)",
            run_id,
            reason_codes,
        )

    import time
    t0 = time.monotonic()
    _timeout_s = settings.ac_parser_llm_timeout_seconds
    logger.info(
        "[%s] Stage 1 BDD normalization: invoking Bedrock (model=%s, prompt=%d chars, timeout=%ds)",
        run_id,
        settings.bedrock_model_id_parser,
        len(system_prompt),
        _timeout_s,
    )
    try:
        response = await asyncio.wait_for(llm.ainvoke(messages), timeout=_timeout_s)
    except asyncio.TimeoutError as _to_err:
        raise ValueError(
            f"Stage 1 BDD normalization timed out after {_timeout_s}s for run '{run_id}' "
            f"(model={settings.bedrock_model_id_parser}, prompt={len(system_prompt)} chars). "
            f"Tune AC_PARSER_LLM_TIMEOUT_SECONDS to override."
        ) from _to_err
    latency_ms = int((time.monotonic() - t0) * 1000)

    bdd_text = response.content.strip()

    # ── Record metrics ──────────────────────────────────────────
    try:
        run_metrics = get_run_metrics(run_id)
        usage = response.response_metadata.get("usage", {})
        run_metrics.record_llm_call(
            purpose="parser",
            model_id=settings.bedrock_model_id_parser,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=latency_ms,
        )
    except Exception as e:
        logger.warning("[%s] Failed to record Stage 1 metrics: %s", run_id, e)

    logger.info(
        "[%s] Stage 1 BDD normalization complete (%d chars)",
        run_id,
        len(bdd_text),
    )
    logger.debug("[%s] BDD output:\n%s", run_id, bdd_text[:500])

    return bdd_text


# ---------------------------------------------------------------------------
# Stage 2 — JSON Compiler
# ---------------------------------------------------------------------------


async def _stage_2_compile(
    bdd_text: str,
    run_id: str,
    product: str | None = None,
) -> TestPlan:
    """
    Stage 2: Compile BDD text into a validated TestPlan.

    FEAT-114: Uses ``instructor`` over raw ``boto3`` for deterministic
    Pydantic-validated JSON output.  The Instructor client handles schema
    validation and retry internally (``max_retries=2``), eliminating the
    brittle ``json.loads`` + ``_repair_json`` loop.

    Args
    ----
    bdd_text : str
        Clean BDD scenario text from Stage 1.
    run_id : str
        Run identifier for logging.

    Returns
    -------
    TestPlan
        Validated structured test plan.

    Raises
    ------
    ValueError
        If the LLM output cannot be validated against TestPlan after
        Instructor's internal retry budget is exhausted.
    """
    # ``instructor`` and ``boto3`` are module-level imports (patchable in tests)
    # ``time`` is in stdlib — imported at module top.

    # MIGRATION: Inject profile-sourced domain glossary and system boundary.
    # When the active product is one that does NOT use the profile's widget
    # stack (e.g. legacy vpromotions vs. Angular/PrimeNG vsuite profile),
    # SUPPRESS the glossary — its component identifiers would poison the
    # target fields with wrong widget tags. The product-specific stack hint
    # appended below carries the correct guidance instead.
    _product_lower = (product or "").lower()
    _suppress_profile_glossary = bool(_product_lower) and _product_lower not in ("", "vsuite", "vpromedia")
    try:
        from backend.profiles import get_active_profile as _gap_parser  # noqa: PLC0415

        _parser_profile = _gap_parser()
        _glossary = "" if _suppress_profile_glossary else _parser_profile.domain_glossary
        _boundary = "" if _suppress_profile_glossary else _parser_profile.system_boundary_rule
    except Exception:
        _glossary = ""  # No profile available — empty glossary
        _boundary = ""  # No profile available — empty boundary

    if _suppress_profile_glossary:
        logger.info(
            "[%s] Stage 2: SUPPRESSED profile glossary for product='%s' — using product-scoped stack hint instead",
            run_id, product,
        )

    system_prompt = JSON_COMPILER_PROMPT.format(
        bdd_scenario_text=bdd_text,
        domain_glossary_section=_glossary,
        system_boundary_rule=_boundary,
    )

    # Product widget-stack guard — mirrors Stage 1. Prevents the JSON
    # compiler from emitting steps whose target selector includes PrimeNG
    # component tags (p-multiselect, p-fileupload, ...) when the product
    # does not use PrimeNG. Applied as a supplemental instruction after the
    # base prompt so the Instructor tool-use schema still binds correctly.
    _stack_hint = _get_product_stack_hint(product)
    if _stack_hint:
        system_prompt += (
            "\n\n"
            "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓\n"
            f"⚠ AUTHORITATIVE PRODUCT CONSTRAINT — OVERRIDES EARLIER GUIDANCE ⚠\n"
            f"Active product: {product}\n"
            "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓\n"
            "This product has TWO PHASES with different widget stacks. See the\n"
            "detailed spec below and choose target names appropriate to each\n"
            "step's phase:\n"
            "  • PHASE 1 (SSO auth + product picker on two-test.vcreative.net):\n"
            "    PrimeNG is IN USE. p-inputtext, p-password, p-button are OK\n"
            "    for the email / password / LOGIN / product-tile steps.\n"
            "  • PHASE 2 (inside vpromotions-rc.vcreative.net/…/promo):\n"
            "    PrimeNG is NOT in use. For every step that happens AFTER the\n"
            "    user is inside the vPromotions app, target MUST be a generic\n"
            "    descriptor:\n"
            "      'button', 'dropdown', 'text-input', 'checkbox', 'file-upload',\n"
            "      'modal', 'toast', 'textarea', 'date-input'.\n"
            "    PrimeNG identifiers FORBIDDEN inside PHASE 2:\n"
            "      p-multiselect, p-fileupload, p-dropdown, p-calendar,\n"
            "      p-radiobutton, p-checkbox, p-toast, p-dialog, p-confirmdialog,\n"
            "      p-autocomplete, p-selectbutton, p-table.\n"
            "  Any earlier instruction telling you 'always use PrimeNG' is\n"
            "  wrong for PHASE 2 and MUST be disregarded there.\n"
            "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓\n"
            f"{_stack_hint}"
            "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓\n"
        )

    # Create a raw boto3 Bedrock client and patch it with Instructor.
    # BEDROCK_TOOLS mode uses Claude's native tool-use feature for deterministic
    # schema-enforced JSON — more reliable than MD_JSON on Bedrock Converse API.
    # The synchronous create call is wrapped in run_in_executor so it doesn't
    # block the asyncio event loop during the Bedrock round-trip (5–20s on Sonnet).
    bedrock_client = boto3.client(
        "bedrock-runtime",
        region_name=settings.aws_bedrock_region,
    )
    instructor_client = instructor.from_bedrock(bedrock_client, mode=instructor.Mode.BEDROCK_TOOLS)

    t0 = time.monotonic()
    _timeout_s = settings.ac_parser_llm_timeout_seconds
    # Stage 2 uses `instructor` over raw boto3 (not langchain), so unlike Stage 1
    # there is no third-party pre-call log. Emit our own so operators can
    # distinguish "hung inside Bedrock" from "hung between stages".
    logger.info(
        "[%s] Stage 2 Instructor JSON compilation: invoking Bedrock "
        "(model=%s, bdd=%d chars, max_retries=2, timeout=%ds)",
        run_id,
        settings.bedrock_model_id_parser,
        len(bdd_text),
        _timeout_s,
    )
    try:
        loop = asyncio.get_event_loop()
        plan, raw_response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: instructor_client.messages.create_with_completion(
                    model=settings.bedrock_model_id_parser,
                    max_tokens=8192,
                    # temperature=0.0: Stage 2 is the dominant source of run-to-run
                    # step-count drift on the same ticket. Instructor's v2 Bedrock
                    # handler forwards this kwarg into inferenceConfig.temperature.
                    # Without it, Bedrock defaults to non-zero sampling and each
                    # parse of the same BDD yields a different step count.
                    temperature=0.0,
                    system=[{"text": system_prompt}],  # Bedrock converse API: system must be a list of dicts
                    messages=[
                        {
                            "role": "user",
                            "content": [{"text": "Compile the BDD scenario above into a valid TestPlan JSON object."}],
                        }
                    ],
                    response_model=TestPlan,
                    max_retries=2,
                ),
            ),
            timeout=_timeout_s,
        )
    except asyncio.TimeoutError as exc:
        raise ValueError(
            f"Stage 2 Instructor compilation timed out after {_timeout_s}s for run '{run_id}' "
            f"(model={settings.bedrock_model_id_parser}, bdd={len(bdd_text)} chars). "
            f"Tune AC_PARSER_LLM_TIMEOUT_SECONDS to override."
        ) from exc
    except Exception as exc:
        raise ValueError(
            f"Stage 2 Instructor compilation failed for run '{run_id}': {exc}"
        ) from exc

    latency_ms = int((time.monotonic() - t0) * 1000)

    # Record metrics — raw_response from create_with_completion contains Bedrock usage
    try:
        run_metrics = get_run_metrics(run_id)
        usage = raw_response.get("usage", {}) if isinstance(raw_response, dict) else {}
        run_metrics.record_llm_call(
            purpose="parser",
            model_id=settings.bedrock_model_id_parser,
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
            latency_ms=latency_ms,
        )
    except Exception as e:
        logger.warning("[%s] Failed to record Stage 2 metrics: %s", run_id, e)

    # Ensure every step has at least one verification (safety net)
    for step in plan.steps:
        if not step.verification:
            step.verification.append(
                Verification(
                    type="element_visible",
                    expected_text=step.goal,
                )
            )

    logger.info(
        "[%s] Stage 2 Instructor compilation complete: %d steps, title='%s', latency=%dms",
        run_id,
        len(plan.steps),
        plan.test_title[:60],
        latency_ms,
    )

    # ── T2-a: Min/Max step gate (heuristic guard against LLM step-count drift) ──
    # Estimate a plausible step count from the BDD text by splitting on ordered-
    # list markers (numbered "1. ", "2. " etc.) and blank-line-separated paragraphs.
    # If the compiled step count falls outside a 0.5x–3x window of this estimate,
    # log a warning — the caller can use this to detect non-deterministic parses
    # before they reach the execution engine.
    _estimated_steps = _estimate_step_count_from_bdd(bdd_text)
    if _estimated_steps > 0:
        _min_expected = max(1, int(_estimated_steps * 0.5))
        _max_expected = max(1, int(_estimated_steps * 3.0))
        _actual = len(plan.steps)
        if _actual < _min_expected or _actual > _max_expected:
            logger.warning(
                "[%s] T2-a step-count gate: compiled %d steps but heuristic estimate is %d "
                "(window: %d–%d). Possible non-determinism — result logged but not blocked.",
                run_id,
                _actual,
                _estimated_steps,
                _min_expected,
                _max_expected,
            )
        else:
            logger.debug(
                "[%s] T2-a step-count gate: %d steps within expected window %d–%d (estimate=%d)",
                run_id,
                _actual,
                _min_expected,
                _max_expected,
                _estimated_steps,
            )

    return plan


# ---------------------------------------------------------------------------
# T2-a: Step-count heuristic estimator
# ---------------------------------------------------------------------------


def _estimate_step_count_from_bdd(bdd_text: str) -> int:
    """
    Estimate the number of AC steps encoded in BDD text without an LLM call.

    Strategy (in priority order):
    1. Count distinct ordered-list markers ("1. ", "2. ", ...) — most BDD
       exports use numbered lists; this is the highest-fidelity signal.
    2. Count "When " / "And " lines — each typically maps to one user action
       that becomes one AC step.
    3. If neither signal fires, return 0 (no estimate available).

    This is used ONLY as a heuristic gate to detect extreme step-count
    drift (> 3x or < 0.5x the estimate), NOT as a hard validator.

    Returns
    -------
    int
        Estimated step count, or 0 if the text is empty or unparseable.
    """
    if not bdd_text or not bdd_text.strip():
        return 0

    # Strategy 1: numbered list markers
    import re as _re
    numbered = _re.findall(r"^\s*\d+\.\s", bdd_text, _re.MULTILINE)
    if numbered:
        return len(numbered)

    # Strategy 2: BDD action lines (When / And — each a distinct step)
    action_lines = _re.findall(r"^\s*(?:When|And)\s+\S", bdd_text, _re.MULTILINE | _re.IGNORECASE)
    if action_lines:
        return max(1, len(action_lines))

    # Strategy 3: non-empty paragraph count (rough proxy)
    paragraphs = [p.strip() for p in _re.split(r"\n\s*\n", bdd_text) if p.strip()]
    return max(0, len(paragraphs) - 1)  # -1 to skip the scenario header paragraph


# ---------------------------------------------------------------------------
# Fallback: legacy parser (same logic as the old inline ac_parser_node)
# ---------------------------------------------------------------------------


async def _fallback_legacy_parse(
    raw_ac: str,
    summary: str,
    run_id: str,
) -> list[str]:
    """
    Fallback: parse AC into a flat list of goal strings (legacy format).

    Used when the two-stage pipeline fails — ensures the agent can still
    run even if structured output isn't available.

    Returns
    -------
    list[str]
        Plain goal strings, same format as the old parser.
    """
    logger.warning(
        "[%s] Falling back to legacy AC parser (flat string list)",
        run_id,
    )

    llm = _get_parser_llm(max_tokens=2048)

    system_prompt = (
        "You are a QA test analyst. Parse the following Jira ticket into a "
        "numbered list of HIGH-LEVEL WORKFLOW GOALS that a human QA tester would follow.\n\n"
        "Output ONLY a JSON array of strings — no commentary, no markdown.\n\n"
        "CRITICAL RULES:\n"
        "- Aim for 5-12 steps total. NEVER produce more than 15 steps.\n"
        "- Each step should be a GOAL, not a click-by-click instruction.\n"
        "- Start with login if the ticket mentions logging in as a specific role.\n"
        "- Keep each step under 150 characters.\n"
        "- Focus on WHAT to achieve, not HOW to click.\n"
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Ticket: {summary}\n\nRequirements:\n{raw_ac}"),
    ]

    response = await llm.ainvoke(messages)
    raw_text = response.content.strip()

    # Strip markdown fences
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, list):
            steps = [str(s) for s in parsed if s]
        else:
            steps = [line.strip() for line in raw_ac.split("\n") if line.strip()]
    except json.JSONDecodeError:
        steps = [line.strip() for line in raw_ac.split("\n") if line.strip()]

    # Run quality validation
    valid_steps, _, _legacy_warnings = validate_ac_steps(steps)
    return valid_steps or steps


async def _rank_attachments(
    attachments: list[dict],
    ac_text: str,
    run_id: str,
) -> list[dict]:
    """
    Rank attachments by relevance to the AC text using a fast LLM.
    (Simulates CLIP-based selection for high-attachment tickets).
    """
    if len(attachments) <= 5:
        return attachments

    llm = _get_parser_llm(max_tokens=512)  # Use parser model tier (Sonnet) for ranking

    # Build a simplified list of attachment metadata for the LLM
    meta = [
        {"id": a["id"], "filename": a["filename"], "mimeType": a.get("mimeType", "")}
        for a in attachments
    ]

    prompt = (
        "You are a QA Engineer. Given the following Acceptance Criteria and a list of Jira attachments, "
        "identify the top 5 attachments that are most likely to contain visual mockups or UI references "
        "relevant to the test. Return ONLY a comma-separated list of attachment IDs in priority order.\n\n"
        f"Acceptance Criteria:\n{ac_text}\n\n"
        f"Attachments:\n{json.dumps(meta, indent=2)}\n\n"
        "IDs:"
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        # ── Record metrics for ranking call ──
        run_metrics = get_run_metrics(run_id)
        usage = response.response_metadata.get("usage", {})
        run_metrics.record_llm_call(
            purpose="parser",
            model_id=settings.bedrock_model_id_parser,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=0, # Latency not tracked for this helper
        )

        id_list = [id.strip() for id in response.content.strip().split(",") if id.strip()]

        # Sort attachments based on the returned ID order
        id_to_att = {a["id"]: a for a in attachments}
        ranked = [id_to_att[id] for id in id_list if id in id_to_att]

        # Add any missing attachments to the end (just in case)
        remaining = [a for a in attachments if a["id"] not in id_list]
        return (ranked + remaining)[:len(attachments)]

    except Exception as e:
        logger.warning("[%s] Attachment ranking failed: %s. Falling back to date sort.", run_id, e)
        return attachments


async def _get_visual_context(state: VQAState) -> str:
    """
    Fetch and analyze Jira attachments to extract visual context.

    Filters for supported image types, downloads them, and runs
    vision analysis. Aggregate results into a single string.
    """
    run_id = state["run_id"]
    attachments = state["jira_ticket"].get("attachments", [])
    ac_text = state["jira_ticket"].get("acceptance_criteria", "")

    if not attachments:
        return ""

    # Supported types and limits from TASK-047/TASK-054; video/mp4 added in TASK-122
    SUPPORTED_TYPES = ["image/png", "image/jpeg", "image/jpg", "image/webp", "application/pdf", "video/mp4"]
    MAX_ATTACHMENTS = 5  # Increased from 3 in TASK-054

    candidates = [
        a
        for a in attachments
        if a.get("mimeType") in SUPPORTED_TYPES and a.get("size", 0) < 10 * 1024 * 1024  # 10MB
    ]

    if not candidates:
        return ""

    # ── Phase 5: Rank candidates by relevance (CLIP-like simulation) ────
    if len(candidates) > MAX_ATTACHMENTS:
        logger.info("[%s] %d candidates found. Ranking for relevance...", run_id, len(candidates))
        candidates = await _rank_attachments(candidates, ac_text, run_id)

    # Sort by created date descending (newest first) for same-rank items
    # Actually, if we ranked them, we should trust the rank.
    targets = candidates[:MAX_ATTACHMENTS]

    logger.info("[%s] Found %d visual attachment(s). Analyzing top %d.", run_id, len(candidates), len(targets))

    analyzer = VisionAnalyzer()
    summaries = []

    import asyncio

    async def process_one(att):
        try:
            content = await download_attachment(att["id"])
            if att.get("mimeType") == "video/mp4":
                logger.info("[%s] Processing MP4 attachment: %s", run_id, att.get("filename", att["id"]))
                return await analyzer.analyze_video(content, ac_text, run_id=run_id)
            return await analyzer.analyze_image(content, att["mimeType"], ac_text, run_id=run_id)
        except Exception as e:
            logger.warning("[%s] Failed to analyze attachment %s: %s", run_id, att["id"], e)
            return ""

    results = await asyncio.gather(*(process_one(t) for t in targets))
    summaries = [r for r in results if r]

    if not summaries:
        return ""

    joined = "\n\n".join(
        f"--- Visual Context from Attachment '{targets[i]['filename']}': ---\n{s}" for i, s in enumerate(summaries) if s
    )
    return joined


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------


async def ac_parser_node(state: VQAState) -> dict:
    """
    LangGraph node: Parse raw Acceptance Criteria into a structured
    test plan using a two-stage LLM pipeline.

    Stage 1 — BDD Normalizer:
        Converts messy Jira AC text into clean Given/When/Then BDD format.
        Expands implicit preconditions (login, navigation, page state).

    Stage 2 — JSON Compiler:
        Compiles BDD text into a strict ``TestPlan`` JSON, validated against
        the Pydantic ``TestPlan`` schema. Maps UI terms to PrimeNG component
        identifiers and generates programmatic verification assertions.

    Dual-Write Output:
        - ``test_plan``: full structured plan (dict from TestPlan.model_dump())
        - ``acceptance_criteria_steps``: legacy string list (step.goal values)

    If the structured pipeline fails, falls back to the legacy flat parser
    to ensure the agent can always run.

    Args
    ----
    state : VQAState
        Must contain ``jira_ticket`` with ``acceptance_criteria``.

    Returns
    -------
    dict
        Partial state update:
        - ``jira_ticket``: updated with ``acceptance_criteria_steps``
        - ``test_plan``: compiled TestPlan dict (or None on fallback)
        - ``structured_step_index``: 0
    """
    # ── Pinned-plan short-circuit (Lock B) ───────────────────────────────────
    # When state["pinned_plan"] is set, the caller opted into byte-identical
    # replay via a pre-authored plan_id.  Return the pinned plan verbatim —
    # BEFORE any cache lookup, BEFORE any LLM call, BEFORE any KB guidance
    # fetch.  This is the load-bearing invariant:
    #   _stage_1_normalize.call_count == 0
    #   _stage_2_compile.call_count == 0
    # Never add a fallback here.  A missing / expired plan_id is a 404/410 at
    # the route layer (Phase 4) — the caller chose pin; it never silently
    # degrades to re-parse.
    _pinned_plan: dict | None = state.get("pinned_plan")
    if _pinned_plan is not None:
        _pinned_plan_id: str | None = state.get("pinned_plan_id")
        logger.info(
            "[%s] pinned_plans HIT %s",
            state.get("run_id", "unknown"),
            _pinned_plan_id or "<no-id>",
        )
        # Build the legacy acceptance_criteria_steps list from the pinned steps
        # so downstream consumers that still read this field are unaffected.
        _pinned_steps = _pinned_plan.get("steps", [])
        _ac_steps: list[str] = [
            step.get("goal", "") for step in _pinned_steps if step.get("goal")
        ]
        return {
            "test_plan": _pinned_plan,
            "jira_ticket": {
                **state.get("jira_ticket", {}),
                "acceptance_criteria_steps": _ac_steps,
            },
            "structured_step_index": 0,
        }
    # ── End pinned-plan short-circuit ────────────────────────────────────────

    run_id: str = state["run_id"]
    raw_ac: str = state["jira_ticket"].get("acceptance_criteria", "")
    summary: str = state["jira_ticket"].get("summary", "")
    description: str = state["jira_ticket"].get("description", "")
    pre_parse_guidance: str = state.get("pre_parse_guidance", "") or ""
    ticket_id: str = state["jira_ticket"].get("ticket_id", "")
    # critic-pass-llm-evaluator (Phase 2): read critic_feedback for retry pass.
    # When non-None, _stage_1_normalize appends a HumanMessage with the critic's
    # guidance so the normalizer can address the detected AC-vs-TestPlan mismatch.
    critic_feedback: dict | None = state.get("critic_feedback")
    detected_paths: list[str] = _detect_nav_paths(raw_ac)
    if detected_paths:
        logger.info(
            "[%s] Path detection: found %d navigation path(s) in raw AC",
            run_id,
            len(detected_paths),
        )
    else:
        logger.debug("[%s] Path detection: no navigation paths found in raw AC", run_id)

    # ── Pre-flight: fetch saved human guidance for this ticket from KB ────
    # human_guidance.md is written by persist_user_guidance() every time the
    # operator provides pre-run guidance or completes a HITL takeover.  Entries
    # are tagged with the ticket_id in their KEYWORDS line, so querying
    # "{ticket_id} human guidance" retrieves them via TF-IDF in O(ms).
    #
    # The fetched text is:
    #   a) merged with pre_parse_guidance so Stage 1 BDD normalizer has history
    #   b) written into state["user_guidance"] so the planner's existing
    #      GLOBAL_HUMAN_GUIDANCE block injects it into EVERY planner prompt
    #      for the remainder of the run — zero additional planner changes needed.
    _fetched_guidance: str = ""
    if ticket_id:
        try:
            import asyncio as _asyncio  # noqa: PLC0415

            from backend.kb.loader import kb as _kb  # noqa: PLC0415

            def _query_guidance() -> str:
                _kb.reload_if_updated()
                # Query 1: ticket-specific guidance
                result = _kb.query(f"{ticket_id} human guidance instructions", max_results=2)
                # Query 2: any operator-flagged guidance for this ticket's summary
                if summary:
                    extra = _kb.query(f"{summary[:80]} human-guidance operator", max_results=1)
                    if extra and extra not in result:
                        result = (result + "\n---\n" + extra).strip() if result else extra
                return result or ""

            loop = _asyncio.get_event_loop()
            _fetched_guidance = await loop.run_in_executor(None, _query_guidance)
            if _fetched_guidance:
                logger.info(
                    "[%s] Pre-flight KB fetch: found %d chars of saved guidance for ticket '%s'",
                    run_id,
                    len(_fetched_guidance),
                    ticket_id,
                )
            else:
                logger.debug(
                    "[%s] Pre-flight KB fetch: no saved guidance found for ticket '%s'",
                    run_id,
                    ticket_id,
                )
        except Exception as _kb_err:
            logger.warning(
                "[%s] Pre-flight KB guidance fetch failed (non-fatal): %s",
                run_id,
                _kb_err,
            )

    # Merge fetched KB guidance with operator-supplied pre_parse_guidance.
    # Fetched guidance goes FIRST so the LLM reads historical context before
    # operator notes (operator notes are typically more specific/recent).
    if _fetched_guidance:
        pre_parse_guidance = (f"[SAVED GUIDANCE FOR {ticket_id}]\n{_fetched_guidance}\n\n" + pre_parse_guidance).strip()

    # Expose the merged guidance as user_guidance in the state patch so that
    # _build_system_prompt()'s GLOBAL_HUMAN_GUIDANCE block picks it up on every
    # planner tick for this run, without any additional planner changes.
    _merged_user_guidance: str = pre_parse_guidance or state.get("user_guidance", "") or ""

    # ── Short-circuit: caller supplied pre-confirmed steps ────────────
    # Check this BEFORE the cache so user edits from the review screen are
    # never silently discarded by a cache hit from the preceding preview call.
    override_steps: list[str] = state.get("override_ac_steps", [])
    if override_steps:
        logger.info(
            "[%s] Using %d user-confirmed override AC steps",
            run_id,
            len(override_steps),
        )
        updated_ticket = dict(state["jira_ticket"])
        updated_ticket["acceptance_criteria_steps"] = override_steps
        global_ctx = await build_global_context(
            override_steps, ticket_id, product=state.get("active_product")
        )

        # ── Cache reuse + defensive step_type recovery ────────────────
        # Fetch the cached preview result up-front for two purposes:
        #  1. If the override text is byte-identical to the cached preview's
        #     step goals (user reviewed but did not edit), reuse the cached
        #     structured plan verbatim — skips a re-compile that can hit the
        #     8192-token output cap for large plans and silently discard
        #     step_type/target_user info the graph relies on.
        #  2. If we DO end up re-compiling and it fails, positionally merge
        #     critical step_types (GHOST_LOGIN / PERSONA_SWITCH) from the
        #     cached preview back onto the plain-text override so the graph
        #     router still fires correctly.
        cached_preview_plan: dict | None = None
        cached_preview_goals: list[str] = []
        try:
            from backend.jira.cache import get_ac_step_cache as _get_ac_cache_early  # noqa: PLC0415

            _early_cache = _get_ac_cache_early()
            _cached_preview_result = await _early_cache.get(
                domain=settings.jira_domain,
                ticket_id=ticket_id,
                guidance=pre_parse_guidance,
                ticket_data=state["jira_ticket"],
            )
            if _cached_preview_result:
                _plan = _cached_preview_result.get("test_plan")
                if isinstance(_plan, dict):
                    cached_preview_plan = _plan
                    _steps = _plan.get("steps") or []
                elif _plan is not None:
                    cached_preview_plan = _plan.model_dump() if hasattr(_plan, "model_dump") else None
                    _steps = getattr(_plan, "steps", []) or []
                else:
                    _steps = []
                cached_preview_goals = [
                    (s.get("goal") if isinstance(s, dict) else getattr(s, "goal", ""))
                    for s in _steps
                ]
        except Exception as _cache_err:
            logger.debug(
                "[%s] Override path: preview cache lookup failed (non-fatal): %s",
                run_id, _cache_err,
            )

        test_plan_dict: dict | None = None

        # Fix B: reuse cached preview plan verbatim when override text is
        # unchanged from what the user reviewed. Skips the doomed re-compile.
        if cached_preview_plan and cached_preview_goals == override_steps:
            logger.info(
                "[%s] Override matches cached preview verbatim — reusing structured plan (%d steps, skipping Stage 2 re-compile)",
                run_id,
                len(cached_preview_goals),
            )
            test_plan_dict = cached_preview_plan
        else:
            # Re-run Stage 2 on a minimal BDD derived from the user's goal
            # strings so the planner retains step_type, target_component,
            # and verification hints even when the user edited steps.
            logger.info(
                "[%s] Re-compiling override steps to TestPlan (Stage 2)",
                run_id,
            )
            try:
                bdd_lines = [
                    "Scenario: User-confirmed acceptance criteria",
                    "",
                    "Given the user is authenticated in the application",
                    "",
                ]
                for goal in override_steps:
                    bdd_lines.append(f"When {goal}")
                    bdd_lines.append("Then verify the action completed correctly")
                    bdd_lines.append("")
                minimal_bdd = "\n".join(bdd_lines)

                compiled_plan = await _stage_2_compile(minimal_bdd, run_id, product=state.get("active_product"))

                if len(compiled_plan.steps) == len(override_steps):
                    # Preserve the user's exact goal text — Stage 2 may rephrase it
                    compiled_plan.steps = [
                        step.model_copy(update={"goal": override_steps[i]})
                        for i, step in enumerate(compiled_plan.steps)
                    ]
                    test_plan_dict = compiled_plan.model_dump()
                    logger.info(
                        "[%s] Override steps re-compiled to TestPlan (%d steps)",
                        run_id,
                        len(compiled_plan.steps),
                    )
                else:
                    logger.warning(
                        "[%s] Stage 2 step count mismatch (%d compiled vs %d override)",
                        run_id,
                        len(compiled_plan.steps),
                        len(override_steps),
                    )
            except Exception as _recompile_err:
                logger.warning(
                    "[%s] Stage 2 re-compile for override steps failed: %s",
                    run_id,
                    _recompile_err,
                )

            # Fix C: if re-compile failed OR count-mismatched but the cached
            # preview has critical step_types (GHOST_LOGIN / PERSONA_SWITCH),
            # positionally merge those types back onto the plain-text
            # override. Losing these types silently would break the graph's
            # ghost-login / persona-switch routing.
            if test_plan_dict is None and cached_preview_plan:
                _cached_steps = cached_preview_plan.get("steps") or []
                _critical_types = {"GHOST_LOGIN", "PERSONA_SWITCH"}
                _has_critical = any(
                    (s.get("step_type") if isinstance(s, dict) else "") in _critical_types
                    for s in _cached_steps
                )
                if _has_critical and len(_cached_steps) == len(override_steps):
                    logger.error(
                        "[%s] Stage 2 re-compile failed and cached preview contains critical "
                        "step_types (GHOST_LOGIN/PERSONA_SWITCH) — positionally merging cached "
                        "step_types onto override text to preserve graph routing (%d steps)",
                        run_id,
                        len(override_steps),
                    )
                    _merged_steps = []
                    for i, cached_step in enumerate(_cached_steps):
                        merged = dict(cached_step) if isinstance(cached_step, dict) else {}
                        merged["goal"] = override_steps[i]
                        _merged_steps.append(merged)
                    test_plan_dict = dict(cached_preview_plan)
                    test_plan_dict["steps"] = _merged_steps
                elif _has_critical:
                    logger.error(
                        "[%s] Stage 2 re-compile failed and cached preview has critical "
                        "step_types but step counts differ (%d cached vs %d override) — "
                        "cannot safely merge; falling back to plain-text (GHOST_LOGIN routing "
                        "will not fire)",
                        run_id,
                        len(_cached_steps),
                        len(override_steps),
                    )

            if test_plan_dict is None:
                logger.warning(
                    "[%s] Falling back to plain-text override (no structured step_type info)",
                    run_id,
                )

        return {
            "jira_ticket": updated_ticket,
            "test_plan": test_plan_dict,
            "structured_step_index": 0,
            "target_element_types": [],
            "global_run_context": global_ctx,
            "user_guidance": _merged_user_guidance,
        }

    # ── T2-a: Content-hash disk cache check (FEAT-117) ───────────────────
    # Serves as the canonical baseline for a given raw AC: the first successful
    # parse of a ticket is persisted to storage/ac_parse_cache/<sha256>.json
    # and every subsequent select on the same AC serves that plan verbatim —
    # no LLM calls, deterministic across process restarts.
    #
    # Historical note (pre-2026-08-05): this gate previously required
    # ``not pre_parse_guidance.strip()`` on the theory that guidance alters
    # LLM output. In practice KB guidance drifts run-to-run (semantic RAG
    # top-K rotates) and enrichment drifts (comment set changes), so gating
    # on "no guidance" meant the cache was dead for real tickets — one KB
    # match and every subsequent run re-paid the ~3-minute parse. Widening
    # the gate makes the disk cache the promoted-baseline mechanism the
    # user actually wants; users who need a fresh parse pass
    # force_reparse=true on /preview-steps to invalidate.
    if raw_ac.strip():
        _disk_cached = _content_cache.get(raw_ac)
        if _disk_cached is not None:
            logger.info(
                "[%s] ac_parser_node: content-hash disk-cache HIT for %s — skipping LLM parsing (canonical baseline)",
                run_id,
                ticket_id,
            )
            _disk_cached = dict(_disk_cached)  # shallow copy
            _disk_cached["user_guidance"] = _merged_user_guidance
            return _disk_cached

    # ── AC Step Cache check (TASK-069) ──────────────────────────────────
    from backend.jira.cache import get_ac_step_cache

    _ac_cache = get_ac_step_cache()
    cached_result = await _ac_cache.get(
        domain=settings.jira_domain,
        ticket_id=ticket_id,
        guidance=pre_parse_guidance,
        ticket_data=state["jira_ticket"],
    )

    if cached_result:
        logger.info(
            "[%s] ac_parser_node: cache HIT for %s — skipping LLM parsing",
            run_id,
            ticket_id,
        )
        # Update user_guidance in the cached result to match current merged value
        # (in case the KB lookup returned something new but the hash matched).
        cached_result["user_guidance"] = _merged_user_guidance
        return cached_result

    # ── Empty AC fallback ─────────────────────────────────────────────
    if not raw_ac.strip():
        logger.warning("[%s] Empty requirements — using fallback step", run_id)
        fallback_step = "Navigate to the application and verify the page loads successfully."
        updated_ticket = dict(state["jira_ticket"])
        updated_ticket["acceptance_criteria_steps"] = [fallback_step]
        global_ctx = await build_global_context(
            [fallback_step], ticket_id, product=state.get("active_product")
        )
        return {
            "jira_ticket": updated_ticket,
            "test_plan": None,
            "structured_step_index": 0,
            "target_element_types": [],  # FEAT-025
            "global_run_context": global_ctx,
            "user_guidance": _merged_user_guidance,
            "detected_paths": detected_paths,
            "ambiguities": [],
        }

    # ── FEAT-001: AC Quality Gate ─────────────────────────────────────
    # Score raw AC text BEFORE Stage 1 BDD normalization.
    quality_result = score_ac_quality(raw_ac)
    initial_score = quality_result.overall_score

    logger.info(
        "[%s] AC Quality Gate (initial): score=%d/10, grade=%s, warnings=%d",
        run_id,
        quality_result.overall_score,
        quality_result.quality_grade,
        len(quality_result.warnings),
    )

    # ── TASK-096 / FEAT-077: FAIR Guardrail ──────────────────────────
    # If quality_grade == "fair" AND the operator has not already provided
    # guidance or approved the bypass, pause the node and broadcast a
    # pre_parse_guidance_required WS event.  The graph loop blocks on an
    # asyncio.Event until the operator responds via POST /run/{run_id}/resume.
    #
    # Bypass conditions (guardrail is SKIPPED when either is True):
    #   a) pre_parse_guidance is already set (guidance from this run or re-run)
    #   b) pre_parse_guidance_approved is True (operator clicked "Proceed Anyway")
    _pre_parse_guidance_approved: bool = state.get("pre_parse_guidance_approved", False) or False
    _has_existing_guidance: bool = bool(pre_parse_guidance and pre_parse_guidance.strip())

    if (
        quality_result.quality_grade == "fair"
        and not _has_existing_guidance
        and not _pre_parse_guidance_approved
    ):
        logger.info(
            "[%s] FAIR guardrail: FAIR-grade detected (score=%d/10) — pausing for operator guidance",
            run_id,
            quality_result.overall_score,
        )

        # Broadcast the WS event so the frontend shows the guidance panel
        await _broadcast_pre_parse_guidance_required(
            run_id=run_id,
            warnings=quality_result.warnings,
            quality_grade=quality_result.quality_grade,
            overall_score=quality_result.overall_score,
        )

        # Set up and block on the asyncio.Event.
        # Use any pre-existing event (created by tests or routes.py) so the
        # test can pre-set it to avoid blocking.  Do NOT clear pre-existing
        # events — clearing would break tests that pre-set the event to True.
        if run_id not in _pre_parse_events:
            _event = asyncio.Event()
            _pre_parse_events[run_id] = _event
        else:
            _event = _pre_parse_events[run_id]
            # Only clear if not already set (allows test pre-set to pass through)
            # In production the event starts unset; in tests it may be pre-set.

        # Signal to the astream loop and _run_states that we are paused
        try:
            from backend.api.routes import _run_states  # noqa: PLC0415
            if run_id in _run_states:
                _run_states[run_id]["status"] = "paused"
                _run_states[run_id]["awaiting_pre_parse_guidance"] = True
        except ImportError:
            pass  # Test environment — no routes module

        # Block until the operator responds
        logger.info("[%s] FAIR guardrail: awaiting operator response (blocking on asyncio.Event)", run_id)
        await _event.wait()
        logger.info("[%s] FAIR guardrail: operator responded — resuming AC parsing", run_id)

        # Clean up the event
        _pre_parse_events.pop(run_id, None)

        # Pull updated state from _resume_data
        try:
            from backend.api.routes import _resume_data, _run_states  # noqa: PLC0415
            _resume_payload = _resume_data.pop(run_id, {})
            _new_guidance = _resume_payload.get("pre_parse_guidance") or ""
            _new_approved = _resume_payload.get("pre_parse_guidance_approved") or False

            if _new_guidance:
                # Operator provided guidance text — merge with existing
                if _new_guidance.strip() not in pre_parse_guidance:
                    pre_parse_guidance = (_new_guidance.strip() + "\n\n" + pre_parse_guidance).strip()
                logger.info(
                    "[%s] FAIR guardrail: injecting operator guidance (%d chars) into Stage 1",
                    run_id,
                    len(_new_guidance),
                )
            elif _new_approved:
                logger.info(
                    "[%s] FAIR guardrail: operator approved bypass ('Proceed Anyway') — proceeding without guidance",
                    run_id,
                )

            # Restore running status
            if run_id in _run_states:
                _run_states[run_id]["status"] = "running"
                _run_states[run_id]["awaiting_pre_parse_guidance"] = False
        except ImportError:
            pass  # Test environment

        # Re-merge guidance for the planner context
        _merged_user_guidance = pre_parse_guidance or state.get("user_guidance", "") or ""

    elif quality_result.quality_grade == "fair" and (_has_existing_guidance or _pre_parse_guidance_approved):
        # Re-run or operator already acted — skip guardrail, log at INFO
        if _pre_parse_guidance_approved:
            logger.info(
                "[%s] FAIR guardrail: bypass approved flag set — proceeding without guidance (score=%d/10)",
                run_id,
                quality_result.overall_score,
            )
        else:
            logger.info(
                "[%s] FAIR guardrail: skipping — pre_parse_guidance already present (%d chars)",
                run_id,
                len(pre_parse_guidance),
            )

    # ── FEAT-002 / FEAT-070: Domain-Aware AC Enrichment & LLM Repair ──
    # Enrich raw AC text with domain context or repair it if quality is sub-GOOD (< 7).
    # This runs as part of the ingestion flow.
    enrichment = await enrich_ac_text(raw_ac, summary, description, ticket_id, quality_result)
    enriched_ac = enrichment.enriched_ac

    # Update quality_dict after enrichment/repair is applied
    quality_dict = quality_result.to_dict()

    if enrichment.enrichment_applied:
        if initial_score < 7:
            logger.info(
                "[%s] FEAT-070 LLM enrichment applied: %d domain(s), +%d chars. "
                "New Quality Score: %d/10 (%s)",
                run_id,
                len(enrichment.detected_domains),
                enrichment.enrichment_char_count,
                quality_result.overall_score,
                quality_result.quality_grade,
            )
        else:
            logger.info(
                "[%s] FEAT-002 enrichment applied: %d domain(s), %d article(s), +%d chars",
                run_id,
                len(enrichment.detected_domains),
                len(enrichment.kb_articles_used),
                enrichment.enrichment_char_count,
            )

    # ── FEAT-001/070: Hard-Reject Post-Repair Poor Quality ────────────
    # If even after LLM-driven repair the AC evaluates to "poor", we abort.
    if quality_result.quality_grade == "poor":
        logger.warning(
            "[%s] AC Quality Gate REJECTED: score=%d/10 (poor). "
            "User must refine ACs before re-submitting. Warnings: %s",
            run_id,
            quality_result.overall_score,
            "; ".join(quality_result.warnings[:5]),
        )
        updated_ticket = dict(state["jira_ticket"])
        # Return the raw split steps so the user can see what the quality gate evaluated
        # and refine them in the UI editor.
        split_steps = split_ac_into_steps(raw_ac)
        updated_ticket["acceptance_criteria_steps"] = split_steps

        return {
            "jira_ticket": updated_ticket,
            "test_plan": None,
            "structured_step_index": 0,
            "global_run_context": "",
            "user_guidance": _merged_user_guidance,
            "ac_quality_result": quality_dict,
            "parse_quality": "rejected",
            "parse_quality_reason": (
                f"AC Quality Gate rejected input (score {quality_result.overall_score}/10). "
                f"Refine the acceptance criteria below to meet the quality standards."
            ),
            "detected_paths": detected_paths,
            "ambiguities": [],
        }

    logger.info(
        "[%s] Starting two-stage structured AC parsing (%d chars of AC, %d enriched)",
        run_id,
        len(raw_ac),
        len(enriched_ac),
    )

    # ── FEAT-045: Visual Context Enrichment ─────────────────────────
    # Fetch and analyze Jira attachments BEFORE normalization.
    visual_context = await _get_visual_context(state)
    if visual_context:
        logger.info(
            "[%s] Injected visual context from %d attachment(s)", run_id, visual_context.count("--- Visual Context")
        )

    # ── Two-stage structured parsing ──────────────────────────────────
    try:
        # Stage 1: BDD normalization (using enriched AC text and visual context).
        # Pass the active product so widget-stack constraints reach the LLM —
        # without this, Stage 1 defaults to PrimeNG-shaped steps (p-multiselect,
        # p-fileupload, etc.) regardless of the actual product's UI framework.
        bdd_text = await _stage_1_normalize(
            enriched_ac,
            summary,
            description,
            run_id,
            visual_context=visual_context,
            pre_parse_guidance=pre_parse_guidance,
            critic_feedback=critic_feedback,  # critic-pass-llm-evaluator (Phase 2)
            product=state.get("active_product"),
        )

        # ── FEAT-058: Ambiguity Pre-Check ──────────────────────────────
        # Detect vague goals in BDD text before JSON compilation.
        # Warnings are injected into the final state so the user can be notified.
        ambiguity_warnings = _detect_step_ambiguity(bdd_text)
        if ambiguity_warnings:
            logger.warning(
                "[%s] Ambiguity detected in BDD text: %d warning(s)",
                run_id,
                len(ambiguity_warnings),
            )

        # Stage 2: JSON compilation → TestPlan
        compiled_plan = await _stage_2_compile(bdd_text, run_id, product=state.get("active_product"))

        # ── T3-d: AC Parse Drift Guard ────────────────────────────────
        # Assert that compiled step count is within ±AC_PARSE_DRIFT_TOLERANCE
        # of the per-ticket baseline in storage/ac_parse_baseline/.
        # Raises ACParseDriftError on tracked-ticket drift > tolerance.
        # Un-tracked tickets write a provisional baseline and continue.
        _drift_guard = ACParseDriftGuard()
        try:
            _drift_result = _drift_guard.assert_drift(
                ticket_key=ticket_id,
                current_step_count=len(compiled_plan.steps),
                raw_ac=raw_ac,
                run_id=run_id,
            )
        except ACParseDriftError as _drift_err:
            logger.error(
                "[%s] T3-d AC_PARSE_DRIFT: ticket=%s baseline=%d current=%d delta=%d — terminating run",
                run_id,
                _drift_err.ticket_key,
                _drift_err.baseline_step_count,
                _drift_err.current_step_count,
                _drift_err.delta,
            )
            raise  # Caught by ac_parser_node outer except; sets failure_type=AC_PARSE_DRIFT

        # ── Dual-write: populate both formats ─────────────────────────
        legacy_steps = [step.goal for step in compiled_plan.steps]
        test_plan_dict = compiled_plan.model_dump()

        # Run legacy quality validation on the goal strings
        valid_steps, validation_errors, validation_warnings = validate_ac_steps(legacy_steps)
        if validation_errors:
            logger.warning(
                "[%s] %d/%d structured step goals failed legacy validation "
                "(keeping all — structured plan has richer data)",
                run_id,
                len(validation_errors),
                len(legacy_steps),
            )

        logger.info(
            "[%s] Structured AC parsing complete: %d steps, test_title='%s'",
            run_id,
            len(compiled_plan.steps),
            compiled_plan.test_title[:60],
        )

        # Log step summary
        for step in compiled_plan.steps:
            verifications = ", ".join(v.type for v in step.verification)
            logger.info(
                "[%s]   Step %d [%s]: %s → target=%s, verify=[%s]",
                run_id,
                step.step_id,
                step.step_type,
                step.goal[:50],
                step.target_component,
                verifications,
            )

        updated_ticket = dict(state["jira_ticket"])
        updated_ticket["acceptance_criteria_steps"] = legacy_steps

        # Preflight: build global run context from the full step list
        global_ctx = await build_global_context(
            legacy_steps, ticket_id, product=state.get("active_product")
        )

        # Auto-detect failed login test scenarios so the AUTH_GATE is bypassed
        # without requiring the caller to manually set expect_login_failure=True.
        _failed_login_signals = [
            "invalid password",
            "invalid email",
            "invalid username",
            "invalid credentials",
            "invalid login",
            "wrong password",
            "wrong email",
            "wrong username",
            "wrong credentials",
            "wrong login",
            "incorrect password",
            "incorrect email",
            "incorrect username",
            "incorrect credentials",
            "incorrect login",
            "bad credentials",
            "failed login",
            "login failure",
            "login error",
            "no jwt",
            "not authenticated",
            "remain on login",
        ]
        _all_steps_text = " ".join(legacy_steps).lower()
        _auto_expect_login_failure = not state.get("expect_login_failure", False) and any(
            sig in _all_steps_text for sig in _failed_login_signals
        )
        if _auto_expect_login_failure:
            logger.info(
                "[%s] Auto-detected failed login test — setting expect_login_failure=True",
                run_id,
            )

        # ── Step 4: Final State Update ─────────────────────────────────────
        # ac_parser node returns the full test_plan and resets the step
        # index to 0 for the start of the test run.
        first_step_roles = []
        if test_plan_dict and test_plan_dict.get("steps"):
            first_step = test_plan_dict["steps"][0]
            first_step_roles = first_step.get("target_element_types", [])

        # Pre-flight strict blocking for Ghost Login impersonation steps.
        # Skipped when running as a preview — preview-steps has no WebSocket
        # and no user to provide credentials, so the 300s wait would always
        # timeout and degrade the 44-step structured plan to the legacy parser.
        # Credentials are an execution concern; the UI prompts for them before
        # the run starts (same pattern as pre_parse_guidance_approved).
        has_ghost_login = test_plan_dict and any(s.get("step_type") == "GHOST_LOGIN" for s in test_plan_dict.get("steps", []))
        # Fallback: when structured parser fell back to legacy, detect ghost via quality gate warnings
        if not has_ghost_login:
            has_ghost_login = any("GHOST_CREDENTIALS_REQUIRED" in w for w in (quality_dict.get("warnings") or []))
        is_preview = state.get("is_preview", False)
        if has_ghost_login and not is_preview:
            from backend.engine.persona_switch_node import _ghost_creds, _wait_for_ghost_credentials
            if run_id not in _ghost_creds:
                logger.info("[%s] Pre-flight block: GHOST_LOGIN step detected in plan, awaiting Admin credentials", run_id)
                await _wait_for_ghost_credentials(run_id)
        elif has_ghost_login and is_preview:
            logger.info(
                "[%s] Preview mode: GHOST_LOGIN step detected but skipping credential gate "
                "(exec-time concern — UI will prompt before /execute)",
                run_id,
            )

        result = {
            "jira_ticket": updated_ticket,
            "test_plan": test_plan_dict,
            "multi_actor_test_plan": None,
            "structured_step_index": 0,
            "target_element_types": first_step_roles,  # FEAT-025
            "global_run_context": global_ctx,
            "user_guidance": _merged_user_guidance,
            "visual_context": visual_context,
            "ac_quality_result": quality_dict,  # FEAT-001
            "ac_enrichment_result": enrichment.to_dict() if enrichment.enrichment_applied else None,  # FEAT-002
            "parse_quality": quality_result.quality_grade,
            "parse_quality_reason": (
                f"AC quality is {quality_result.quality_grade} (score {quality_result.overall_score}/10). "
                f"Some steps may be vague: {'; '.join(quality_result.warnings[:2])}"
                if quality_result.quality_grade == "fair"
                else None
            ),
            "detected_paths": detected_paths,
            "ambiguities": ambiguity_warnings,
            **({"expect_login_failure": True} if _auto_expect_login_failure else {}),
        }

        # Cache the result for future runs of the same ticket + guidance (TASK-069)
        await _ac_cache.set(
            domain=settings.jira_domain,
            ticket_id=ticket_id,
            guidance=pre_parse_guidance,
            ticket_data=state["jira_ticket"],
            result=result,
        )

        # T2-a: persist to content-hash disk cache as the canonical baseline.
        # First successful parse of a ticket becomes the version served on all
        # subsequent selects — see the corresponding GET block above for the
        # rationale on why guidance no longer gates this write.
        if raw_ac.strip():
            _content_cache.set(raw_ac, result)

        return result

    except ACParseDriftError as _drift_fatal:
        # T3-d: AC parse drift is a first-class failure — no fallback to legacy parser.
        # The run terminates with failure_type=AC_PARSE_DRIFT.
        logger.error(
            "[%s] AC_PARSE_DRIFT terminal failure: ticket=%s baseline=%d current=%d delta=%d",
            run_id,
            _drift_fatal.ticket_key,
            _drift_fatal.baseline_step_count,
            _drift_fatal.current_step_count,
            _drift_fatal.delta,
        )
        return {
            "failure_type": "AC_PARSE_DRIFT",
            "status": "failed",
            "jira_ticket": state.get("jira_ticket", {}),
            "test_plan": None,
            "structured_step_index": 0,
            "target_element_types": [],
            "global_run_context": {},
            "user_guidance": "",
            "visual_context": None,
            "ac_quality_result": quality_dict,
            "ac_enrichment_result": None,
            "parse_quality": "failed",
            "parse_quality_reason": str(_drift_fatal),
            "detected_paths": [],
            "ambiguities": [],
            "ac_parse_drift": {
                "baseline_step_count": _drift_fatal.baseline_step_count,
                "current_step_count": _drift_fatal.current_step_count,
                "delta": _drift_fatal.delta,
            },
        }

    except Exception as e:
        _fallback_reason = str(e)[:300]
        logger.error(
            "[%s] Structured AC parsing failed: %s — falling back to legacy parser",
            run_id,
            _fallback_reason,
        )

        # Fallback to legacy flat parser
        steps = await _fallback_legacy_parse(raw_ac, summary, run_id)

        logger.info("[%s] Legacy fallback parsed %d steps", run_id, len(steps))

        updated_ticket = dict(state["jira_ticket"])
        updated_ticket["acceptance_criteria_steps"] = steps

        # Preflight still runs even on fallback path
        global_ctx = await build_global_context(
            steps, ticket_id, product=state.get("active_product")
        )

        result = {
            "jira_ticket": updated_ticket,
            "test_plan": None,  # No structured plan available
            "structured_step_index": 0,
            "target_element_types": [],  # FEAT-025
            "global_run_context": global_ctx,
            "user_guidance": _merged_user_guidance,
            "visual_context": visual_context,
            "ac_quality_result": quality_dict,  # FEAT-001
            "ac_enrichment_result": enrichment.to_dict() if enrichment.enrichment_applied else None,  # FEAT-002
            # Surfaces degraded parse quality to the planner so it knows to reason more carefully
            "parse_quality": "degraded",
            "parse_quality_reason": _fallback_reason,
            "detected_paths": detected_paths,
            "ambiguities": [],
        }

        # Cache even fallback results to save LLM time on repeat failures (TASK-069)
        await _ac_cache.set(
            domain=settings.jira_domain,
            ticket_id=ticket_id,
            guidance=pre_parse_guidance,
            ticket_data=state["jira_ticket"],
            result=result,
        )

        # T2-a: fallback results are NOT stored in the content-hash disk cache.
        # The fallback path indicates Stage 1+2 failed; caching a degraded result
        # under the content hash would suppress legitimate retry attempts.

        return result
