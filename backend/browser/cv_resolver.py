"""
cv_resolver.py — CV Fallback Layer: CvFallbackResolver
=======================================================
Module: backend/browser/cv_resolver.py
Feature: FEAT-037 / TASK-028

Implements the executor-side CV recovery path that activates after DOM failure
exhaustion and before HITL escalation.

Phase 1 delivered:
  - CvFallbackResolver.should_activate() — cost gate with threshold + eligibility logic
  - CvFallbackResolver.estimate_cost()   — per-invocation USD cost estimate

Phase 2 delivers:
  - CvFallbackResolver.resolve()  — captures SoM screenshot, calls vision LLM, returns mark_id
  - _invoke_cv_vision_llm()       — stateless Bedrock converse call with JPEG image input
  - _call_bedrock_vision()        — raw Bedrock client wrapper (mockable in tests)
  - _parse_mark_id_from_response() — JSON extraction with regex fallback

Design constraints (from creative/TASK-028-cv-fallback-architecture.md):
  - Stateless vision call: one screenshot in, one mark_id out
  - No shared context with planner's main vision session
  - mark_id validated against mark_coordinate_map before returning
  - cost gate is non-negotiable: never invoke vision LLM on first attempt
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.browser.vision_utils import (
    draw_marks_and_snapshot,
    format_vision_mark_summary,
)

if TYPE_CHECKING:
    pass  # Page type used only for annotation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Eligible action types for CV fallback
# ---------------------------------------------------------------------------
_CV_ELIGIBLE_ACTION_TYPES: frozenset[str] = frozenset({"click", "coordinate_action"})

# ---------------------------------------------------------------------------
# Reduced threshold when cv_fallback_eligible=True on an action
# ---------------------------------------------------------------------------
_ELIGIBLE_ACTION_THRESHOLD: int = 1


class CvFallbackResolver:
    """
    Executor-side CV recovery path.

    Responsibilities (phased):
      Phase 1: Cost gate (should_activate) + cost accounting (estimate_cost)
      Phase 2: Vision LLM call (resolve) + executor integration
      Phase 3: State change detection (cv_fallback_state_change_check)

    Design:
      - Stateless vision call: one screenshot in, one mark_id out
      - No shared context with planner's main vision session
      - Validates mark_id is within mark_coordinate_map before returning
      - Cost gate is non-negotiable: never invoke on first attempt

    Usage (Phase 2+)::

        resolver = CvFallbackResolver()
        if resolver.should_activate(state, action, enabled=True, min_dom_failures=3):
            mark_id, mark_map, cost = await resolver.resolve(page, target_desc)
            if mark_id is not None:
                coords = mark_map[str(mark_id)]
                await page.mouse.click(coords["x"], coords["y"])
    """

    def should_activate(
        self,
        state: dict,
        action: dict,
        *,
        enabled: bool,
        min_dom_failures: int,
    ) -> bool:
        """
        Return True iff CV fallback should fire for this action.

        Cost gate logic (all conditions must hold):
          1. ``enabled`` flag must be True
          2. ``action["action"]`` must be in {``click``, ``coordinate_action``}
          3. ``state["ac_step_action_fail_count"] >= min_dom_failures``
             OR (``cv_fallback_eligible=True`` on action AND fail_count >= 1)
          4. CV fallback has NOT already been attempted on ``state["ac_step_index"]``
             (prevents a double vision call on the same step)
        """
        # ── Gate 1: Feature flag ────────────────────────────────────────
        if not enabled:
            logger.debug("CV_FALLBACK_GATE: disabled by feature flag")
            return False

        # ── Gate 2: Action type eligibility ─────────────────────────────
        action_type = action.get("action", "")
        if action_type not in _CV_ELIGIBLE_ACTION_TYPES:
            logger.debug("CV_FALLBACK_GATE: action_type=%r not eligible", action_type)
            return False

        # ── Gate 3: Failure count threshold ─────────────────────────────
        fail_count: int = state.get("ac_step_action_fail_count", 0)
        cv_fallback_eligible: bool = bool(action.get("cv_fallback_eligible", False))

        if cv_fallback_eligible:
            threshold = _ELIGIBLE_ACTION_THRESHOLD
        else:
            threshold = min_dom_failures

        if fail_count < threshold:
            logger.debug(
                "CV_FALLBACK_GATE: fail_count=%d < threshold=%d (eligible=%s)",
                fail_count,
                threshold,
                cv_fallback_eligible,
            )
            return False

        # ── Gate 4: Per-step double-invocation guard ─────────────────────
        current_step_idx: int = state.get("ac_step_index", 0)
        cv_results: list[dict] = state.get("cv_fallback_results", [])
        already_attempted_this_step = any(r.get("step_idx") == current_step_idx for r in cv_results)
        if already_attempted_this_step:
            logger.debug(
                "CV_FALLBACK_GATE: already attempted CV fallback on step_idx=%d — skipping",
                current_step_idx,
            )
            return False

        logger.debug(
            "CV_FALLBACK_GATE: ACTIVATING — fail_count=%d threshold=%d step_idx=%d eligible=%s",
            fail_count,
            threshold,
            current_step_idx,
            cv_fallback_eligible,
        )
        return True

    async def resolve(
        self,
        page: object,  # playwright.async_api.Page
        target_description: str,
        existing_mark_map: dict | None = None,
        existing_screenshot_b64: str | None = None,
        visual_context: str | None = None,
    ) -> tuple[int | None, dict, float]:
        """
        Capture annotated screenshot, call vision LLM, return mark_id.

        Returns
        -------
        tuple[int | None, dict, float]
            ``(mark_id | None, mark_coordinate_map, cost_estimate_usd)``

        On any failure (closed page, screenshot error, LLM null/error, mark_id
        not in map), returns ``(None, mark_map_or_{}, cost)`` — never raises.
        """
        cost = self.estimate_cost()

        # ── Gate: closed page ─────────────────────────────────────────────
        if page.is_closed():
            logger.warning("CV_FALLBACK_RESOLVE: page is closed — skipping")
            return None, {}, cost

        # ── Step 1: Capture SoM annotated screenshot ──────────────────────
        mark_map: dict = {}
        screenshot_b64: str = ""

        if existing_mark_map and existing_screenshot_b64:
            mark_map = existing_mark_map
            screenshot_b64 = existing_screenshot_b64
            logger.debug("CV_FALLBACK_RESOLVE: reusing existing mark_map (%d entries)", len(mark_map))
        else:
            try:
                screenshot_b64, mark_map = await draw_marks_and_snapshot(page)
                logger.info("CV_FALLBACK_RESOLVE: SoM snapshot captured — %d marks", len(mark_map))
            except Exception as snap_err:
                logger.error("CV_FALLBACK_RESOLVE: snapshot failed: %s", snap_err)
                return None, {}, cost

        if not mark_map:
            logger.warning("CV_FALLBACK_RESOLVE: no interactive elements found on page")
            return None, {}, cost

        # ── Step 2: Build vision prompt summary ───────────────────────────
        mark_summary = format_vision_mark_summary(mark_map)

        # ── Step 3: Call vision LLM (stateless) ───────────────────────────
        mark_id: int | None = await _invoke_cv_vision_llm(
            screenshot_b64=screenshot_b64,
            mark_summary=mark_summary,
            target_description=target_description,
            visual_context=visual_context,
        )

        # ── Step 4: Validate mark_id exists in the coordinate map ─────────
        if mark_id is not None and str(mark_id) not in mark_map:
            logger.warning(
                "CV_FALLBACK_RESOLVE: LLM returned mark_id=%d not in coordinate map (available: %s) — rejecting",
                mark_id,
                list(mark_map.keys())[:10],
            )
            mark_id = None

        if mark_id is not None:
            coords = mark_map[str(mark_id)]
            logger.info(
                "CV_FALLBACK_ACTIVATED: mark_id=%d → (%d, %d) tag=%s target=%r",
                mark_id,
                coords["x"],
                coords["y"],
                coords.get("tag", "?"),
                target_description[:60],
            )
        else:
            logger.warning(
                "CV_FALLBACK_RESOLUTION_FAILED: could not identify target=%r in screenshot",
                target_description[:60],
            )

        return mark_id, mark_map, cost

    def estimate_cost(self) -> float:
        """
        Return estimated USD cost per vision call.

        Based on Claude 3.5 Sonnet vision pricing at 1024px image input.
        Approximately $0.003 per invocation (input tokens ~1500 at $3/MTok).

        Used by the executor to populate ``cost_estimate`` in each
        ``cv_fallback_results`` entry for the audit report.
        """
        return 0.003


# ---------------------------------------------------------------------------
# Module-level vision LLM helpers (Phase 2)
# ---------------------------------------------------------------------------

_CV_VISION_SYSTEM_PROMPT = (
    "You are a UI element locator. You are given an annotated screenshot where "
    "interactive elements are numbered with red bounding boxes. "
    "Identify which numbered mark corresponds to the target element described. "
    'Respond ONLY with a JSON object: {"mark_id": <integer>} '
    'or {"mark_id": null} if the target is not visible in the screenshot.'
)


async def _invoke_cv_vision_llm(
    screenshot_b64: str,
    mark_summary: str,
    target_description: str,
    visual_context: str | None = None,
) -> int | None:
    """
    Call Claude (via Bedrock) with the annotated screenshot and return mark_id.

    Returns ``int`` mark_id on success, ``None`` on any failure or null response.
    Never raises — all exceptions are caught and logged.
    """
    context_prefix = f"Visual context from Jira attachments: {visual_context}\n\n" if visual_context else ""
    user_text = (
        f"{context_prefix}"
        f"{mark_summary}\n\n"
        f"Target element: {target_description}\n\n"
        f'Respond with JSON only: {{"mark_id": <integer or null>}}'
    )

    try:
        image_bytes = _b64_to_bytes(screenshot_b64)
        user_content = [
            {
                "image": {
                    "format": "jpeg",
                    "source": {"bytes": image_bytes},
                }
            },
            {"text": user_text},
        ]

        response = await _call_bedrock_vision(
            system_prompt=_CV_VISION_SYSTEM_PROMPT,
            user_content=user_content,
        )
        result = _parse_mark_id_from_response(response)
        logger.info("CV_FALLBACK_VISION_CALL: LLM returned mark_id=%s", result)
        return result
    except Exception as err:
        logger.error("CV_FALLBACK_LLM: Bedrock call failed: %s", err)
        return None


def _b64_to_bytes(b64_str: str) -> bytes:
    """Decode a base64 string to bytes for Bedrock image input."""
    import base64

    return base64.b64decode(b64_str)


async def _call_bedrock_vision(
    system_prompt: str,
    user_content: list[dict],
) -> dict:
    """
    Invoke the Bedrock converse API with vision (image) content.

    Uses the heavy model (Claude Sonnet) — Haiku does not support vision input.
    Mockable in tests via ``patch("backend.browser.cv_resolver._call_bedrock_vision")``.
    """
    import asyncio

    import boto3

    from backend.config import settings

    bedrock = boto3.client("bedrock-runtime", region_name=settings.aws_bedrock_region)
    model_id = settings.bedrock_model_id_heavy  # Vision requires Sonnet

    response = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: bedrock.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": user_content}],
            inferenceConfig={"maxTokens": 64, "temperature": 0.0},
        ),
    )
    return response


def _parse_mark_id_from_response(response: dict) -> int | None:
    """
    Extract mark_id integer from a Bedrock converse response dict.

    Handles three cases:
    - Valid JSON: ``{"mark_id": 5}``  → returns 5
    - Null JSON:  ``{"mark_id": null}`` → returns None
    - Non-JSON or missing text → returns None
    """
    import json
    import re

    try:
        content_blocks = response["output"]["message"]["content"]
        for block in content_blocks:
            text = block.get("text", "")
            if not text:
                continue
            # Strategy 1: direct JSON parse
            try:
                parsed = json.loads(text.strip())
                if isinstance(parsed, dict):
                    val = parsed.get("mark_id")
                    return int(val) if val is not None else None
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
            # Strategy 2: regex extraction from surrounding prose
            match = re.search(r'"mark_id"\s*:\s*(\d+|null)', text)
            if match:
                raw = match.group(1)
                return None if raw == "null" else int(raw)
    except Exception as parse_err:
        logger.debug("CV_FALLBACK_LLM: response parse error: %s", parse_err)

    return None
