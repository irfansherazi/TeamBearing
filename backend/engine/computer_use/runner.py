"""
The Computer-Use loop.

    fetch_ticket → launch_browser → ghost_login → loop:
        screenshot → Claude → tool → screenshot → repeat
    until: done | request_help (→ HITL) | step cap | wall-clock cap

Deliberately small. The whole file is under 400 lines. Anything that starts
looking like scaffolding gets rejected — the whole point of this rewrite is
to prove that a minimal loop drives the app.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from backend.browser.context import BrowserManager, register_manager, unregister_manager
from backend.config import settings
from backend.engine.computer_use.prompts import SYSTEM_PROMPT, build_user_message
from backend.engine.computer_use.tools import TOOL_SCHEMAS, dispatch_tool
from backend.jira.client import fetch_ticket_context

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Loop configuration
# ---------------------------------------------------------------------------

# Real form-filling on enterprise SPAs takes many iterations (QA-359 needed
# 60+ just to reach the required-field validation step). Keep both caps as a
# safety net against runaway loops, but set them generously and env-configurable
# so nobody has to touch code to widen them. Hard cap enforcement lives in the
# API-layer Pydantic model (backend/api/routes.py :: ExecuteCURequest).
DEFAULT_MAX_ITERATIONS = int(os.environ.get("VQA_CU_MAX_ITERATIONS", "300"))
DEFAULT_MAX_WALL_SECONDS = int(os.environ.get("VQA_CU_MAX_WALL_SECONDS", "3600"))  # 1 hour


def _model_id() -> str:
    """
    Pick the Bedrock inference-profile ID for the Computer-Use loop.

    Priority:
      1. VQA_CU_MODEL_ID env var (override, e.g. us.anthropic.claude-opus-5)
      2. Default: us.anthropic.claude-sonnet-5 — same computer-use +
         browser-automation capability tier as Opus 5, ~2.5× cheaper per
         token, 1M context. Opus 5 remains available via env override.

    We deliberately do NOT reuse settings.bedrock_model_id_heavy —
    that field still points to the legacy Sonnet 4 profile used by the
    LangGraph pipeline, which AWS Bedrock now rejects for fresh boto3
    Converse calls. The Computer-Use loop needs its own live model ID.
    """
    return os.environ.get("VQA_CU_MODEL_ID") or "us.anthropic.claude-sonnet-5"


# ---------------------------------------------------------------------------
# Bedrock Converse tool-use loop
# ---------------------------------------------------------------------------


def _get_bedrock_client():
    """Lazy-import boto3 so this module remains importable in test envs.

    Retries: Bedrock frequently returns 503 ``ServiceUnavailableException``
    during regional capacity blips. Legacy boto3 defaults (4 attempts, fixed
    backoff) exhausted mid-run on QA-359 before iteration 1 completed. We
    switch to ``adaptive`` mode with ``max_attempts=10`` so the client uses
    a token-bucket throttle-aware backoff and rides out multi-minute Bedrock
    saturation instead of killing the loop. Timeouts are widened to match
    (Converse with a large cached prefix can legitimately take >60s).
    """
    import boto3
    from botocore.config import Config
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    max_attempts = int(os.environ.get("VQA_CU_BEDROCK_MAX_ATTEMPTS", "10"))
    cfg = Config(
        retries={"max_attempts": max_attempts, "mode": "adaptive"},
        connect_timeout=15,
        read_timeout=120,
    )
    return boto3.client("bedrock-runtime", region_name=region, config=cfg)


def _tool_config() -> dict[str, Any]:
    """Convert Anthropic-style tool schemas → Bedrock Converse tool spec."""
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": {"json": t["input_schema"]},
                }
            }
            for t in TOOL_SCHEMAS
        ]
    }


# Anthropic's Computer-Use guidance grounds best on screenshots <= ~1280 wide.
# Larger images (retina @ 2x, 4K displays) cost more tokens and localize worse.
_MAX_SCREENSHOT_WIDTH = int(os.environ.get("VQA_CU_MAX_SCREENSHOT_WIDTH", "1280"))


async def _viewport_css_size(page) -> tuple[int, int]:
    """
    Return the CSS-pixel viewport size (what page.mouse.click(x,y) expects).

    In headless mode Playwright sets an explicit viewport → page.viewport_size
    is authoritative. In headed --start-maximized mode the context is created
    with viewport=None → page.viewport_size is None; fall back to
    window.innerWidth / innerHeight via JS evaluation.
    """
    vp = page.viewport_size
    if vp and vp.get("width") and vp.get("height"):
        return int(vp["width"]), int(vp["height"])
    try:
        dims = await page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
        return int(dims["w"]), int(dims["h"])
    except Exception:
        # Last-ditch default — matches DEFAULT_VIEWPORT in browser/context.py
        return 1920, 1080


async def _screenshot_png_bytes(page) -> bytes:
    """
    Full-viewport PNG screenshot, downsampled for LLM consumption.

    Also stashes coordinate-conversion metadata on `page._vqa_click_meta`
    so `tool_click_at` can translate model-emitted screenshot pixels back
    into Playwright's CSS pixel space. The metadata reflects the screenshot
    THIS call is about to return.
    """
    raw = await page.screenshot(type="png", full_page=False)

    # Original PNG dims (device-pixel resolution on retina; matches CSS *
    # devicePixelRatio).
    try:
        from PIL import Image  # local import — Pillow is a heavy dep
        with Image.open(io.BytesIO(raw)) as im:
            orig_w, orig_h = im.size
            if orig_w > _MAX_SCREENSHOT_WIDTH:
                new_w = _MAX_SCREENSHOT_WIDTH
                new_h = max(1, round(orig_h * (new_w / orig_w)))
                im = im.convert("RGB") if im.mode == "P" else im
                im = im.resize((new_w, new_h), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="PNG", optimize=False)
                out_bytes = buf.getvalue()
                ss_w, ss_h = new_w, new_h
            else:
                out_bytes = raw
                ss_w, ss_h = orig_w, orig_h
    except Exception as e:
        # Never let image processing block the loop — fall back to raw bytes.
        logger.debug("screenshot resize skipped: %s", e)
        out_bytes = raw
        ss_w = ss_h = 0  # unknown — click_at will fall back to identity mapping

    vp_w, vp_h = await _viewport_css_size(page)
    try:
        page._vqa_click_meta = {
            "screenshot_w": ss_w,
            "screenshot_h": ss_h,
            "viewport_w": vp_w,
            "viewport_h": vp_h,
        }
    except Exception:
        pass  # setattr on Playwright Page is safe but guard anyway

    return out_bytes


def _build_screenshot_user_message(png_bytes: bytes, tool_use_id: str, tool_result_text: str) -> dict[str, Any]:
    """A user turn that carries the tool_result + the fresh screenshot."""
    return {
        "role": "user",
        "content": [
            {
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "content": [
                        {"text": tool_result_text},
                        {"image": {"format": "png", "source": {"bytes": png_bytes}}},
                    ],
                    "status": "success",
                }
            }
        ],
    }


def _initial_user_message(user_text: str, png_bytes: bytes) -> dict[str, Any]:
    """
    Initial user turn. The `cachePoint` between the text and image is
    intentional:
      - `user_text` is FIXED for the entire run (AC + numbered steps +
        optional product-specific helper). On turn 2+, Bedrock serves
        that entire prefix from cache at ~1/10 the input price.
      - The initial screenshot is OUTSIDE the cache boundary, so if
        `_prune_old_screenshots` later replaces it with a text
        placeholder, the cached prefix still matches.
    Combined with the system-prompt cachePoint (`_call_bedrock`), this
    gives us TWO cached prefixes stacked: system + initial user text.
    """
    return {
        "role": "user",
        "content": [
            {"text": user_text},
            {"cachePoint": {"type": "default"}},
            {"image": {"format": "png", "source": {"bytes": png_bytes}}},
        ],
    }


async def _call_bedrock(client, model_id: str, messages: list[dict], system_text: str) -> dict:
    """Call Bedrock Converse. boto3 is sync so we run it in an executor.

    Note: Opus 5 (and other reasoning models) reject the `temperature`
    parameter — the model runs at a fixed sampling temperature internally.
    We keep the inferenceConfig minimal.

    Prompt caching: the system prompt is static across an entire run, so we
    annotate it with a Bedrock cachePoint. On call 2+, that prefix reads at
    ~1/10 the input price. The cachePoint MUST be a separate tagged-union
    element after the text block — see backend/engine/prompt_cache.py for
    the shape rationale and the failure mode of combining them.

    On ValidationException we log a compact snapshot of the last-assistant
    content shape before re-raising, so model-behavior mismatches (e.g. a
    new model emitting parallel toolUse blocks the runner didn't reply to)
    are diagnosable from the log alone.
    """
    loop = asyncio.get_event_loop()
    def _sync():
        return client.converse(
            modelId=model_id,
            messages=messages,
            system=[
                {"text": system_text},
                {"cachePoint": {"type": "default"}},
            ],
            toolConfig=_tool_config(),
            inferenceConfig={"maxTokens": 2048},
        )
    try:
        return await loop.run_in_executor(None, _sync)
    except Exception as e:
        if "ValidationException" in type(e).__name__ or "ValidationException" in str(e):
            logger.error(
                "[bedrock] ValidationException — message shape summary: %s",
                _summarize_messages_for_debug(messages),
            )
        raise


def _summarize_messages_for_debug(messages: list[dict]) -> str:
    """
    Compact per-message summary for post-mortem logging.

    Emits e.g. "[user: text+image] [assistant: reasoning+toolUse(id=A,click)+
    toolUse(id=B,fill)] [user: toolResult(A)+image]" so a mismatch between
    toolUse IDs and toolResult IDs is visible at a glance in the log.
    """
    parts: list[str] = []
    for m in messages[-6:]:  # last 6 messages is enough to see the mismatch
        role = m.get("role", "?")
        block_descs: list[str] = []
        for b in m.get("content", []) or []:
            if not isinstance(b, dict):
                continue
            if "text" in b:
                block_descs.append("text")
            elif "image" in b:
                block_descs.append("image")
            elif "reasoningContent" in b:
                block_descs.append("reasoning")
            elif "toolUse" in b:
                tu = b["toolUse"]
                block_descs.append(f"toolUse(id={(tu.get('toolUseId') or '')[:12]},{tu.get('name')})")
            elif "toolResult" in b:
                tr = b["toolResult"]
                block_descs.append(f"toolResult(id={(tr.get('toolUseId') or '')[:12]})")
            else:
                block_descs.append(next(iter(b.keys()), "?"))
        parts.append(f"[{role}: {'+'.join(block_descs) or 'empty'}]")
    return " ".join(parts)


def _extract_tool_uses(response: dict) -> tuple[list[dict], str]:
    """
    Pull EVERY tool_use block from a Bedrock Converse response.

    Returns (tool_calls, model_text_response) where each entry in tool_calls is
    ``{"id": tool_use_id, "name": tool_name, "input": tool_input}``.
    tool_calls is an empty list if the model didn't invoke any tools.

    Parallel tool calls are common on newer Anthropic models — Sonnet 5 emits
    e.g. mark_step_status + click in the same assistant turn. Bedrock validates
    that EVERY tool_use in an assistant message has a matching toolResult in
    the next user message; missing any raises a ValidationException. The
    caller must therefore dispatch and reply to every entry returned here,
    not just the first.
    """
    content = response.get("output", {}).get("message", {}).get("content", [])
    tool_calls: list[dict] = []
    text_parts: list[str] = []
    for block in content:
        if "toolUse" in block:
            tu = block["toolUse"]
            tool_calls.append({
                "id": tu.get("toolUseId"),
                "name": tu.get("name"),
                "input": tu.get("input") or {},
            })
        elif "text" in block:
            text_parts.append(block["text"])
    return tool_calls, "\n".join(text_parts).strip()


def _build_multi_tool_result_message(
    tool_results: list[tuple[str, str]],
    png_bytes: bytes | None = None,
) -> dict[str, Any]:
    """
    Build a single user turn carrying one toolResult per dispatched tool.

    tool_results is a list of ``(tool_use_id, result_text)`` in the order the
    tools were dispatched. The fresh screenshot (if provided) is embedded in
    the LAST toolResult so the model sees post-action page state without
    paying for a duplicate image on each result block.
    """
    content: list[dict] = []
    for idx, (tool_use_id, result_text) in enumerate(tool_results):
        result_content: list[dict] = [{"text": result_text}]
        if png_bytes is not None and idx == len(tool_results) - 1:
            result_content.append({"image": {"format": "png", "source": {"bytes": png_bytes}}})
        content.append({
            "toolResult": {
                "toolUseId": tool_use_id,
                "content": result_content,
                "status": "success",
            }
        })
    return {"role": "user", "content": content}


def _refresh_rolling_cache_point(messages: list[dict]) -> None:
    """
    Manage a single ROLLING ``cachePoint`` at the tail of the conversation.

    Bedrock allows up to 4 cache breakpoints per request. Two are already
    permanent — the system-prompt breakpoint (see ``_call_bedrock``) and the
    initial-user-text breakpoint (see ``_initial_user_message``). This helper
    manages a third, rolling breakpoint that follows the most recent
    ``toolResult`` user message so each turn's growing history gets a real
    cache hit instead of being re-billed at full input price.

    On call N:
      - Any prior rolling breakpoint (a ``cachePoint`` block sitting at the END
        of an older user message that contains ``toolResult`` blocks) is
        removed. We keep exactly ONE rolling breakpoint at any time so we
        never exhaust the 4-breakpoint budget.
      - A fresh ``cachePoint`` block is appended to the tail user message so
        that message ends with the marker.

    On call N+1, Bedrock's prefix match hits everything through the tail of
    call N (cache_read at ~1/10 the price of input), and only the new
    assistant + tool_result delta is billed at full input price. Prior to
    this, ``cache_read`` was stuck at ~11k tokens (the two fixed breakpoints)
    for the entire run — see runner.py's initial cache design commentary.

    The initial-user breakpoint is NEVER touched here because it sits BEFORE
    the initial screenshot block (not at the end of the message), so our
    "trailing cachePoint on a toolResult-carrying user message" filter can't
    match it.

    Cache prefix stability is a co-requirement: ``_prune_old_screenshots``
    was updated to batch its mutations (via ``prune_batch``) so the prefix
    tokens don't change every iteration and defeat the cache. If pruning
    ever runs eagerly again, this helper's cache reads collapse to zero.
    """
    # 1. Strip any prior rolling breakpoint. Walk every user message except
    #    the tail (which is where the new one will go). Only remove a trailing
    #    cachePoint block from user messages that also carry at least one
    #    toolResult — that combination is unmistakably our marker.
    for msg in messages[:-1]:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list) or not content:
            continue
        has_tool_result = any(
            isinstance(b, dict) and "toolResult" in b for b in content
        )
        if not has_tool_result:
            continue
        if isinstance(content[-1], dict) and "cachePoint" in content[-1]:
            content.pop()

    # 2. Add a fresh breakpoint to the tail, if the tail is a user message
    #    with toolResult blocks. Do NOTHING otherwise — an assistant tail or
    #    an initial-user tail means either we're about to append a user turn
    #    (caller's job, not ours) or we're on the very first Bedrock call
    #    (no rolling cache to establish yet).
    if not messages:
        return
    tail = messages[-1]
    if tail.get("role") != "user":
        return
    content = tail.get("content")
    if not isinstance(content, list) or not content:
        return
    has_tool_result = any(
        isinstance(b, dict) and "toolResult" in b for b in content
    )
    if not has_tool_result:
        return
    # Idempotency guard: if this function is somehow called twice before the
    # next append, don't stack two markers on the same message.
    if isinstance(content[-1], dict) and "cachePoint" in content[-1]:
        return
    content.append({"cachePoint": {"type": "default"}})


# ---------------------------------------------------------------------------
# Cost tracking + guardrail
# ---------------------------------------------------------------------------

# Bedrock Anthropic pricing per 1M tokens. Source: AWS Bedrock console pricing
# page as of 2026-08-04. If Anthropic changes pricing, update this table —
# it's the single source of truth for CU cost accounting and the USD cap.
# Cache prices are the 5-minute-TTL tier; the 1h tier is not used by the loop.
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-5":     {"input": 5.00,  "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-sonnet-5":   {"input": 2.00,  "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-fable-5":    {"input": 10.00, "output": 50.00, "cache_read": 1.00, "cache_write": 12.50},
    "claude-opus-4-8":   {"input": 5.00,  "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-7":   {"input": 5.00,  "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-sonnet-4-6": {"input": 3.00,  "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-4-6":   {"input": 5.00,  "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-5":   {"input": 5.00,  "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-haiku-4-5":  {"input": 1.00,  "output": 5.00,  "cache_read": 0.10, "cache_write": 1.25},
    "claude-sonnet-4-5": {"input": 3.00,  "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-sonnet-4":   {"input": 3.00,  "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
}

# Conservative fallback for unrecognized model IDs — bills at Opus tier so we
# never under-cap an unknown model into a runaway run.
_FALLBACK_PRICING = _MODEL_PRICING["claude-opus-5"]

# Hard USD cap. Cumulative cost check runs after every Bedrock response;
# exceeding this halts the run with terminal_status="cost_cap".
DEFAULT_MAX_USD = float(os.environ.get("VQA_CU_MAX_USD", "20.0"))

# Screenshot retention. Older user-message image blocks are replaced with a
# text placeholder ("[Screenshot from iter N — pruned]") so the model still
# knows the turn happened without paying for the ~1.3K image tokens.
#
# Lowered from 10 → 4 alongside the rolling-cache work. Rationale: with a
# working rolling cache breakpoint, EVERY image in the retained window is
# billed as cache_read (~1/10 the input price) on turn 2+ of a stable
# pruning window, so the "10 recent screenshots" ergonomic buffer costs
# ~10× less than it used to — but images the model doesn't need are still
# tokens. Six recent screenshots covers a full multi-field form step (each
# fill = ~1-2 turns, so 6 images ≈ 4 fields of visual history) — enough
# for the model to see what it just filled without re-guessing the state
# of already-completed fields. Was 4; bumped after QA-359 form-fill runs
# where the model kept re-clicking already-filled fields it could no
# longer see in the prompt window.
DEFAULT_KEEP_SCREENSHOTS = int(os.environ.get("VQA_CU_KEEP_SCREENSHOTS", "6"))

# Prune batch size. ``_prune_old_screenshots`` only runs when the total image
# count exceeds ``keep_last_n + prune_batch`` — it then prunes the excess
# down to keep_last_n in one shot. This keeps the message-token sequence
# STABLE for windows of ~prune_batch iterations at a time, which is a hard
# co-requirement for the rolling cache breakpoint managed by
# ``_refresh_rolling_cache_point``. Pruning on every iteration (the pre-fix
# behavior) mutates one message per turn in the middle of the prefix, which
# invalidates the cache and defeats the whole point of the rolling marker.
#
# Cost tradeoff: during the accumulation phase between prunes we hold up to
# prune_batch extra images in the request. Each image is ~1300 tokens, so
# an accumulation of 6 extra images = ~7800 tokens of image content. At
# cache_read prices ($0.20/M for sonnet-5) this is $0.0016 per call —
# effectively free — versus the ~$0.026 per call we'd pay if pruning ran
# every turn and killed the cache. Break-even is at prune_batch ≈ 1, so
# any value ≥ 2 is a net win.
DEFAULT_PRUNE_BATCH = int(os.environ.get("VQA_CU_PRUNE_BATCH", "6"))

# Stuck-iteration guardrail. Progress is signalled by EITHER
# (a) a successful ``mark_step_status`` update, or (b) a "novel action"
# within the currently in_progress step — a (tool, canonical_target)
# signature the model has not attempted in this step yet. If neither
# signal fires for this many consecutive iterations, we terminate with
# terminal_status="stuck".
#
# Why the dual signal: on multi-field forms (QA-359 PRF: 15+ fields
# within a single "Fill out the PRF" step) the model legitimately makes
# progress for 20-40 iters between step marks. Marking only on step
# transitions killed those runs. But when the model bounces on the same
# (click_at, scroll, wait) sequence, no NEW targets appear — the novel-
# action counter never advances and the cap still fires.
#
# Original QA-359 failure mode (run-16a8e2b2): after step 22 (Copy PRF)
# the model spent ~60 iterations bouncing between Actions/Edit-PRF/scroll
# clicks on the same 3 pixel regions — that's what we're catching. New
# QA-359 form-fill mode (run-5595f92d): 19 iters of legitimate novel
# clicks/fills was misclassified as stuck; that's what we're releasing.
DEFAULT_STUCK_ITERATIONS_THRESHOLD = int(os.environ.get("VQA_CU_STUCK_ITERATIONS_THRESHOLD", "20"))

# Widget-hammer stuck signal. Complements the coarse "no step_state change +
# no novel action" cursor above with a targeted rule: if the last W turns
# aggregate >= H hits against the SAME canonical widget (same click target,
# same select2 anchor, same click_at pixel bucket), fire stuck-cap even if
# other steps are being marked in parallel. Catches the QA-359-copy failure
# mode where the model marked step 19/20 passed while burning 60+ iters
# hammering "Copy PRF → Save → look for Delete → not there → Copy PRF again".
# The threshold is on distinct-widget-hit density, not iteration count, so a
# form-fill sweep across 15 different fields keeps advancing.
DEFAULT_WIDGET_HAMMER_WINDOW = int(os.environ.get("VQA_CU_WIDGET_HAMMER_WINDOW", "15"))
DEFAULT_WIDGET_HAMMER_THRESHOLD = int(os.environ.get("VQA_CU_WIDGET_HAMMER_THRESHOLD", "8"))

# Runtime backpressure — code-side belt-and-suspenders backing up
# helper-file guidance the model rationalizes past under context pressure.
# Each backpressure detector counts consecutive turns exhibiting one
# specific anti-pattern; once a detector's threshold is met, its warning
# text is appended to the LAST toolResult text so the model reads it inline
# with the tool output it's about to process. Counter resets on any turn
# that doesn't match the pattern — real progress breaks the loop naturally.
#
# All three thresholds are env-configurable so we can tune without a
# redeploy if genuine slow-enterprise-page traffic triggers false positives.
# Two consecutive wait-only turns is now the trigger (was 3). Observed on
# QA-359 run-da278899: iters 240-242 were three `wait(3s)` calls in a row
# after clicking Save Draft — the drawer had already closed by iter 241
# but the model kept waiting on a spinner that wasn't there. Dropping to
# 2 fires the warning one iter sooner, saving ~5s + $0.02 per stall. The
# helper file now also tells the model NOT to wait after menu opens /
# field clicks / press-Tab, so 2-in-a-row is a genuine anomaly.
_WAIT_BACKPRESSURE_THRESHOLD = int(os.environ.get("VQA_CU_WAIT_BACKPRESSURE_THRESHOLD", "2"))
_SCROLL_CLICK_BACKPRESSURE_THRESHOLD = int(os.environ.get("VQA_CU_SCROLL_CLICK_BACKPRESSURE_THRESHOLD", "3"))
# Restart intent is a one-shot detector — the moment the model articulates
# "restart form", the warning fires. We never want a form-restart to
# proceed uncommented.
_RESTART_INTENT_THRESHOLD = int(os.environ.get("VQA_CU_RESTART_INTENT_THRESHOLD", "1"))
# Fill-failure backpressure fires quickly: two consecutive fill errors is
# usually the locator failing to resolve, and each retry is a wasted Bedrock
# round-trip. Observed on QA-359: model retried fill on the Title field 4×
# before degrading to N × press().
_FILL_FAIL_BACKPRESSURE_THRESHOLD = int(os.environ.get("VQA_CU_FILL_FAIL_BACKPRESSURE_THRESHOLD", "2"))

_WAIT_BACKPRESSURE_WARNING = (
    "\n\n"
    "⚠️ SYSTEM WARNING (from the runner, not from the app): You have "
    "called `wait` on {count} consecutive turns with no other tool. "
    "Further waiting is unlikely to change the screenshot. STOP waiting "
    "and pick ONE of the following on your next turn:\n"
    "  1. If a spinner is still on screen and 30+ seconds have passed, "
    "     treat the request as failed — call "
    "     `mark_step_status(status=\"failed\", note=<what-you-observed>)` "
    "     on the affected step, or `request_help(reason=...)`.\n"
    "  2. If the page has stabilized, take your next REAL action (click, "
    "     fill, press, mark_step_status) — do NOT wait again.\n"
    "  3. Do NOT click a spinner icon to try to \"trigger\" or \"test\" it. "
    "     Spinners mean the app is working; clicking them does nothing "
    "     productive and wastes a full turn.\n"
    "This warning is injected by the runtime — it is not part of the "
    "tool result and will not appear on non-wait turns."
)

_SCROLL_CLICK_BACKPRESSURE_WARNING = (
    "\n\n"
    "⚠️ SYSTEM WARNING (from the runner, not from the app): You have "
    "called `click_at` with a 'scroll'-intent reason on {count} "
    "consecutive turns. Clicking on the drawer's scrollbar edge does "
    "NOT scroll the drawer — the scrollbar isn't a control the browser "
    "reacts to on `mouse.click()`. STOP scroll-by-click and use ONE of "
    "the following on your next turn:\n"
    "  1. `press(\"Tab\")` — advances focus to the next form control and "
    "     auto-scrolls it into view WITHIN the drawer. This is the "
    "     correct scroll primitive for form drawers.\n"
    "  2. `click(target=\"<css-selector-of-target-field>\", hint=\"css\")` "
    "     — Playwright auto-scrolls the locator into view BEFORE the "
    "     click, so a semantic click on the next field is a scroll+click "
    "     in one tool call.\n"
    "  3. If you're genuinely stuck finding the next field, call "
    "     `request_help(reason=...)` rather than continuing to click the "
    "     scrollbar area.\n"
    "PageDown / PageUp are ALSO banned in the drawer — they scroll the "
    "page, not the drawer's scrollable ancestor."
)

_FILL_FAIL_BACKPRESSURE_WARNING = (
    "\n\n"
    "⚠️ SYSTEM WARNING (from the runner, not from the app): Your last "
    "{count} consecutive turns included a `fill` tool that returned an error. "
    "The locator is probably not resolving to the element you see on screen. "
    "STOP retrying `fill` and switch to this approach:\n"
    "  1. `click` or `click_at` on the target field to focus it.\n"
    "  2. `type_text(text=\"your value\")` — types the entire string in one call.\n"
    "Do NOT fall back to individual `press(key)` calls for multi-character strings — "
    "that costs one Bedrock round-trip per character."
)

_RESTART_INTENT_WARNING = (
    "\n\n"
    "🛑 SYSTEM WARNING (from the runner, not from the app): Your last "
    "tool call's reason mentioned RESTARTING the form (\"restart\", "
    "\"start over\", or \"start fresh\"). DO NOT restart the form. "
    "Every field-fill turn already spent on this form (typically $5-10 "
    "of Bedrock spend) will be DISCARDED, and you will hit the cost cap "
    "before completing the AC on the second attempt. Instead:\n"
    "  1. Diagnose why the current form state seems broken. Look at the "
    "     screenshot carefully — the drawer usually IS still there; you "
    "     may just be looking at a scrolled region.\n"
    "  2. If the drawer really did close (e.g. accidental header-logo "
    "     click, accidental Cancel), call `request_help(reason=\"drawer "
    "     state lost — need human recovery\")` — a human can decide "
    "     whether to reopen the drawer or accept partial completion.\n"
    "  3. If you are UNSURE whether restarting is right, ALWAYS prefer "
    "     `request_help` over restarting. The human can restart if that "
    "     is truly the correct move; restarting on your own has never "
    "     been the correct move in a completed AC run."
)


def _is_wait_only_turn(tool_calls: list[dict]) -> bool:
    """True iff every tool call in this turn is `wait`."""
    return bool(tool_calls) and all((c.get("name") or "") == "wait" for c in tool_calls)


def _is_scroll_click_turn(tool_calls: list[dict]) -> bool:
    """
    True iff every tool call is `click_at` AND every reason mentions
    scrolling. This is the drawer-edge scroll-loop signature observed
    on QA-359 (`click_at(1274, ~650, reason="scroll down...")` repeated
    4-6× in a row while the drawer contents don't move).
    """
    if not tool_calls:
        return False
    for c in tool_calls:
        if (c.get("name") or "") != "click_at":
            return False
        reason = str((c.get("input") or {}).get("reason", "")).lower()
        if "scroll" not in reason:
            return False
    return True


# Restart-intent lexicon. Any tool call whose reason or target contains one
# of these phrases signals the model is about to throw away form state and
# start over. Matched case-insensitively as substrings. Kept intentionally
# broad — a false positive costs one warning text block; a false negative
# costs $5-10 of discarded form-fill work.
_RESTART_INTENT_TOKENS = (
    "restart form",
    "restart the form",
    "start over",
    "start fresh",
    "start from scratch",
    "start a new prf",
    "new prf to restart",
    "restart from scratch",
)


def _has_fill_error(tool_results: list[tuple[str, str]]) -> bool:
    """
    True if any tool_result in this turn contains a fill error.

    Unlike the other detectors, this reads tool_results (not tool_calls) —
    we can't tell from the model's request whether the fill will fail; we
    have to wait until after dispatch to know. Match on the exact error
    prefix emitted by tool_fill so we don't trip on unrelated tool errors.
    """
    return any("error: fill" in txt.lower() for _, txt in tool_results)


# Canonical target signatures for the novel-action stuck signal.
#
# Every tool call gets reduced to a (tool_name, target_key) tuple. Within
# the currently in_progress step, the FIRST time a signature appears is
# forward progress — the model is doing something it hasn't tried yet.
# Every subsequent occurrence is a repeat and does NOT reset the stuck
# counter. Signatures are cleared when the step changes (any successful
# mark_step_status), so each step gets a fresh set.
#
# `wait` is deliberately excluded — waiting is not progress by any
# definition, and the existing wait-only backpressure covers that case.
# `mark_step_status`, `done`, and `request_help` are also excluded
# because they have their own accounting paths (step_state changes,
# terminal transitions).
#
# click_at coordinates are bucketed to 20px cells so 1-2px wobble on the
# same visual target counts as one signature. type_text values are
# truncated to 40 chars — long enough to distinguish "Test PRF Contest"
# from "Van Hit prize $500" but short enough that a repeated multi-char
# paste doesn't create pseudo-novelty. press keys are kept exact so a
# Tab-Tab-Escape sequence registers three novel actions the first time
# and zero on subsequent repeats.
_CLICK_AT_BUCKET_PX = 20
_TYPE_TEXT_SIG_LEN = 40


def _normalize_target(s: Any) -> str:
    """Case-fold + whitespace-collapse a target string for signature keys."""
    return " ".join(str(s or "").lower().split())


def _widget_keys(tool_calls: list[dict]) -> list[str]:
    """
    Reduce each tool call to a coarse "widget key" — a canonical identifier
    for the UI element the model is aiming at. Collapses across tool variants
    that target the same widget (e.g. `click` and `click_at` on the same
    Actions button both key to `pixel:60,12`; `click`, `fill`, and `select2_pick`
    on the same field all key to their normalized target string).

    Non-widget-locked calls (`wait`, `mark_step_status`, `done`, `request_help`,
    `press`, `type_text`, `lookup_selector`) return None and are excluded from
    the caller's hammer count — they don't correspond to a single widget.
    """
    keys: list[str] = []
    for c in tool_calls:
        name = (c.get("name") or "").strip()
        inp = c.get("input") or {}
        if name in ("wait", "mark_step_status", "done", "request_help",
                    "press", "type_text", "lookup_selector"):
            continue
        if name == "click_at":
            try:
                x = int(inp.get("x", 0))
                y = int(inp.get("y", 0))
            except (TypeError, ValueError):
                x = y = 0
            # Coarser bucket than action-novelty (which uses _CLICK_AT_BUCKET_PX=20).
            # 60px bucket collapses ~one button-sized region into one key so
            # coordinate-drift within a widget still counts as the same widget.
            keys.append(f"pixel:{x // 60},{y // 60}")
        elif name == "navigate":
            keys.append(f"navigate:{_normalize_target(inp.get('url', ''))}")
        elif name == "select2_pick":
            keys.append(f"widget:{_normalize_target(inp.get('anchor', ''))}")
        elif name in ("click", "fill", "select"):
            keys.append(f"widget:{_normalize_target(inp.get('target', ''))}")
        else:
            # Unknown tool — hash on whole input so it counts as one key.
            keys.append(f"other:{name}:{_normalize_target(json.dumps(inp, sort_keys=True))}")
    return keys


def _tool_call_signatures(tool_calls: list[dict]) -> list[tuple[str, Any]]:
    """
    Reduce each tool call to a (tool_name, target_key) signature.

    Returns one signature per call in order. Non-progress tools (wait,
    mark_step_status, done, request_help) return None-target signatures
    that are filtered out by the caller — they don't count for or
    against novelty.
    """
    sigs: list[tuple[str, Any]] = []
    for c in tool_calls:
        name = (c.get("name") or "").strip()
        inp = c.get("input") or {}
        if name in ("wait", "mark_step_status", "done", "request_help"):
            continue
        if name == "click_at":
            try:
                x = int(inp.get("x", 0))
                y = int(inp.get("y", 0))
            except (TypeError, ValueError):
                x = y = 0
            key = (x // _CLICK_AT_BUCKET_PX, y // _CLICK_AT_BUCKET_PX)
            sigs.append((name, key))
        elif name == "type_text":
            txt = _normalize_target(inp.get("text", ""))[:_TYPE_TEXT_SIG_LEN]
            sigs.append((name, txt))
        elif name == "press":
            sigs.append((name, str(inp.get("key", "")).strip()))
        elif name == "navigate":
            sigs.append((name, str(inp.get("url", "")).strip()))
        elif name in ("click", "fill", "select"):
            sigs.append((name, _normalize_target(inp.get("target", ""))))
        else:
            # Unknown tool — hash on the whole input so novel inputs
            # count but repeats don't.
            sigs.append((name, _normalize_target(json.dumps(inp, sort_keys=True))))
    return sigs


def _has_restart_intent(tool_calls: list[dict]) -> bool:
    """
    True if ANY tool call in this turn articulates restart intent in its
    reason or target field. This fires immediately (threshold 1) — we
    never want a restart to proceed uncommented.
    """
    for c in tool_calls:
        args = c.get("input") or {}
        hay = " ".join([
            str(args.get("reason", "")),
            str(args.get("target", "")),
        ]).lower()
        if any(tok in hay for tok in _RESTART_INTENT_TOKENS):
            return True
    return False


# ---------------------------------------------------------------------------
# Ghost-login enforcement
# ---------------------------------------------------------------------------
#
# Observed on QA-359 run-c5e8c2f0: the model marked the `Perform ghost login
# as Sales Person` step as passed with note "Already ghosting as Sales Person
# per task setup" — but ghost login had NOT been performed (only admin auth
# had). Every subsequent form action ran as the admin persona, silently
# invalidating the run.
#
# The rail below is code-level, not prompt-level: any mark_step_status(status
# in {passed, skipped}) on a ghost-login step is verified against the actual
# top-right persona badge before the update is applied. On mismatch, the
# update is REJECTED, the mark_step_status result is rewritten to an error,
# and a backpressure warning is appended so the model reads the failure
# inline with its next screenshot. This is the same "warning in the last
# tool_result" mechanism the other backpressure detectors use.
#
# Step-text patterns are intentionally broad — the AC parser has emitted at
# least these phrasings: "Perform ghost login as X", "Ghost login as X",
# "Ghost in as X", "Ghost - X". Extraction returns the target name (the
# capture group), or None if the step is ghost-like but no target was
# named — in which case we still verify that the badge is NOT the admin
# any longer (the persona MUST have changed away from admin).

_GHOST_STEP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ghost\s+login\s+as\s+(.+)", re.IGNORECASE),
    re.compile(r"ghost\s+in\s+as\s+(.+)", re.IGNORECASE),
    re.compile(r"ghost\s*[-–—]\s*(.+)", re.IGNORECASE),
    re.compile(r"perform\s+ghost\s+login\s+as\s+(.+)", re.IGNORECASE),
    re.compile(r"perform\s+ghost\s+login", re.IGNORECASE),  # no target named
    re.compile(r"\bghost\s+login\b", re.IGNORECASE),        # no target named
)


def _parse_ghost_target(step_text: str) -> tuple[bool, str | None]:
    """
    Detect a ghost-login step and extract its target user (if named).

    Returns (is_ghost_step, target_name_or_None). target is None when the
    step is unambiguously a ghost-login step but names no user — the caller
    should then verify the badge is NOT still the admin.
    """
    if not step_text:
        return False, None
    for pat in _GHOST_STEP_PATTERNS:
        m = pat.search(step_text)
        if not m:
            continue
        if m.groups():
            target = m.group(1).strip().rstrip(".,;:!?").strip()
            # Strip trailing role qualifiers the parser sometimes appends
            # (e.g. "Sales Person to test PRF creation").
            target = re.split(r"\b(to|and|then|so\s+that|in\s+order)\b", target, maxsplit=1, flags=re.IGNORECASE)[0]
            target = target.strip().rstrip(".,;:!?").strip()
            return True, (target or None)
        return True, None
    return False, None


async def _read_top_right_badge_text(page) -> str:
    """
    Return concatenated visible text from the header's top-right region.

    Josh's product-memory: successful ghost = target user's name shows in
    the top-right persona indicator, universally across vProMedia products
    (vPromotions, vPromedia, vPPO). Rather than hunt for a per-product
    selector, we sample every leaf element whose bounding box sits inside
    the top ~80px band AND the right 40% of the viewport. Empty string on
    any evaluation failure — the caller treats an empty read as
    "verification unavailable" and errs on the side of NOT rejecting
    (fail-open on infra glitches, not on model mistakes).
    """
    try:
        text = await page.evaluate(
            """
            () => {
              const parts = [];
              const vw = window.innerWidth || document.documentElement.clientWidth || 1280;
              const nodes = document.body.querySelectorAll('*');
              for (const el of nodes) {
                if (el.children.length > 0) continue;
                if (!el.offsetParent && el.tagName !== 'BODY') continue;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                if (rect.top < -5 || rect.top > 90) continue;
                if (rect.right < vw * 0.55) continue;
                const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                if (t && t.length > 0 && t.length < 200) parts.push(t);
              }
              return parts.join(' | ');
            }
            """,
        )
        return str(text or "")
    except Exception as e:
        logger.debug("top-right badge read failed: %s", e)
        return ""


def _name_matches_badge(target: str, badge_text: str) -> bool:
    """
    True if ``target`` appears in ``badge_text`` (case-insensitive, tolerant
    of extra whitespace and initials-vs-full-name mismatches).

    Matches BOTH the full string AND each individual word ≥3 chars against
    the badge. This is deliberately permissive — the admin's real display
    name may differ from the target user's stored name by punctuation,
    middle initial, or role suffix ("Josh Schauer" vs "Josh Schauer, Admin").
    A permissive match is fine for the rail because the failure signature
    it protects against is the OPPOSITE: the model marks passed when the
    badge STILL shows a totally different persona.
    """
    if not target or not badge_text:
        return False
    t_norm = re.sub(r"\s+", " ", target).strip().lower()
    b_norm = re.sub(r"\s+", " ", badge_text).lower()
    if t_norm in b_norm:
        return True
    # Word-level: at least one ≥3-char alpha token from target must appear
    # in the badge (allows "Sales Person" ↔ "SP - Sales Person" collisions).
    tokens = [w for w in re.findall(r"[a-zA-Z]{3,}", t_norm)]
    if not tokens:
        return False
    return any(w in b_norm for w in tokens)


async def _verify_ghost_switch(
    page,
    step_text: str,
    admin_email: str,
) -> tuple[bool, str, str | None]:
    """
    Check whether ghost login actually happened for this ghost-login step.

    Returns (verified, badge_text_seen, target_name_or_None).

    Verification rules:
      - Step names a target ("as X"): the top-right badge must contain X
        (permissive word-level match) — this is the strong rail that
        catches QA-359's failure mode.
      - Step names no target ("Perform ghost login"): fail-open. We only
        know the admin's email, and its local-part ("admin") is a common
        substring in header UI ("Return to admin" links, "Admin Panel"
        buttons). A false-positive rejection here is worse than missing
        an ambiguous case — the AC parser overwhelmingly emits the "as X"
        form in practice.
      - Empty badge read → fail-open (infra glitch, not a model mistake).

    admin_email is retained on the signature for future use (e.g. if we
    ever ingest the admin's display name from Jira / SSM) but is not
    currently consumed — see rationale above.
    """
    del admin_email  # reserved for a future stronger untargeted check
    is_ghost, target = _parse_ghost_target(step_text)
    if not is_ghost:
        return True, "", None
    badge = await _read_top_right_badge_text(page)
    if not badge:
        return True, "", target
    if target:
        return _name_matches_badge(target, badge), badge, target
    return True, badge, None


_GHOST_REJECT_WARNING = (
    "\n\n"
    "🛑 SYSTEM WARNING (from the runner, not from the app): You called "
    "`mark_step_status(status={status!r})` on step {index} — a GHOST-LOGIN "
    "step — but the runner independently checked the top-right persona "
    "badge and it does NOT reflect a ghost switch to the target user.\n"
    "  - step text:            {step_text!r}\n"
    "  - target user expected: {target}\n"
    "  - top-right badge seen: {badge!r}\n"
    "Your mark has been REJECTED — the step is still 'in_progress'. Ghost "
    "login has NOT been performed. Do the following now:\n"
    "  1. Click the persona picker in the top-right header (the badge that "
    "     currently shows the admin user).\n"
    "  2. Search for and select the target user named in the step.\n"
    "  3. Confirm the switch and wait for the top-right badge to update.\n"
    "  4. Only THEN call `mark_step_status(status=\"passed\")` on this step.\n"
    "Do NOT mark this step passed/skipped again until the top-right badge "
    "shows the target user's name — the rail will keep rejecting the mark."
)


def _pricing_for(model_id: str) -> dict[str, float]:
    """Match Bedrock model ID against the pricing table by family substring."""
    mid = model_id.lower()
    for key, prices in _MODEL_PRICING.items():
        if key in mid:
            return prices
    return _FALLBACK_PRICING


def _call_cost_usd(usage: dict, prices: dict[str, float]) -> float:
    """
    Compute USD cost from a Bedrock Converse ``usage`` block.

    Bedrock Converse reports cache-read and cache-write tokens as SEPARATE
    fields from ``inputTokens``; the additive formula below is correct for
    that shape. If Bedrock ever changes to bundling cache tokens INSIDE
    inputTokens, this will over-count — the fix is a single subtraction.
    """
    inp = int(usage.get("inputTokens", 0) or 0)
    out = int(usage.get("outputTokens", 0) or 0)
    cache_r = int(usage.get("cacheReadInputTokens", 0) or 0)
    cache_w = int(usage.get("cacheWriteInputTokens", 0) or 0)
    return (
        inp * prices["input"]
        + cache_r * prices["cache_read"]
        + cache_w * prices["cache_write"]
        + out * prices["output"]
    ) / 1_000_000


# ---------------------------------------------------------------------------
# Screenshot pruning
# ---------------------------------------------------------------------------


def _count_image_blocks(msg: dict) -> int:
    """Return the number of image blocks in a message's content (top-level or
    nested inside toolResult)."""
    content = msg.get("content", []) or []
    n = 0
    for block in content:
        if not isinstance(block, dict):
            continue
        if "image" in block:
            n += 1
        elif "toolResult" in block:
            for sub in block["toolResult"].get("content", []) or []:
                if isinstance(sub, dict) and "image" in sub:
                    n += 1
    return n


def _replace_image_blocks_with_placeholder(msg: dict, placeholder: str) -> int:
    """
    Replace every image block in a message with a text placeholder in place.

    Handles both shapes:
      - initial user message:   content = [{"text": ...}, {"image": ...}]
      - tool-result message:    content = [{"toolResult": {"content": [{"text": ...}, {"image": ...}], ...}}]

    Returns the number of image blocks replaced.
    """
    content = msg.get("content", []) or []
    replaced = 0
    for block in content:
        if not isinstance(block, dict):
            continue
        if "image" in block:
            del block["image"]
            block["text"] = placeholder
            replaced += 1
        elif "toolResult" in block:
            sub_content = block["toolResult"].get("content", []) or []
            for sub in sub_content:
                if isinstance(sub, dict) and "image" in sub:
                    del sub["image"]
                    sub["text"] = placeholder
                    replaced += 1
    return replaced


def _prune_old_screenshots(
    messages: list[dict],
    keep_last_n: int,
    prune_batch: int = 0,
) -> int:
    """
    Keep at most ``keep_last_n`` image blocks (from the newest end); replace
    older images with a text placeholder so the model still sees a turn
    marker but pays no image tokens for the pruned frame.

    Pruning is **batched**: this function is a no-op until the total image
    count exceeds ``keep_last_n + prune_batch``, at which point it prunes
    the excess back down to ``keep_last_n`` in one shot. Batching is a
    hard co-requirement for the rolling cache breakpoint managed by
    ``_refresh_rolling_cache_point``:

      - The rolling breakpoint caches the growing conversation prefix. If
        pruning mutates one message per iteration in the middle of that
        prefix (the pre-fix behavior — a single image → placeholder swap
        every turn), the token sequence changes each turn and Bedrock's
        prefix-match cache-lookup fails on every call.
      - With batching, between prune events the token sequence is STABLE,
        so the rolling breakpoint's prefix match succeeds on every call
        and only the new assistant + tool_result delta is billed at full
        input price.
      - On a prune-event iteration the cache does invalidate — that call
        costs full input price for the whole conversation, same as
        pre-fix — but this happens once every prune_batch iterations
        rather than every iteration, so amortized cost is dominated by
        cache_read at ~1/10 the price.

    Callers that need eager prune-every-turn semantics can pass
    ``prune_batch=0`` (matching the pre-fix behavior exactly).

    Returns the number of image blocks pruned this call.
    """
    if keep_last_n < 0:
        return 0
    total_images = sum(_count_image_blocks(m) for m in messages)
    # Batched trigger: only mutate when we're strictly OVER the accumulation
    # budget. Between events the message sequence stays stable and the
    # rolling cache breakpoint gets clean prefix matches.
    if total_images <= keep_last_n + max(0, prune_batch):
        return 0
    to_prune = total_images - keep_last_n
    pruned = 0
    for idx, msg in enumerate(messages):
        if pruned >= to_prune:
            break
        n = _count_image_blocks(msg)
        if n == 0:
            continue
        pruned += _replace_image_blocks_with_placeholder(
            msg, f"[Screenshot pruned — was msg #{idx} in history; see later screenshots for current state]"
        )
    return pruned


# ---------------------------------------------------------------------------
# Ghost login (reused from existing engine — NOT re-implemented)
# ---------------------------------------------------------------------------


async def _apply_role_storage_state(
    page,
    run_id: str,
    target_url: str,
    storage_state_path: str,
) -> None:
    """
    Apply a role's storage-state to the current page and verify authentication.

    Playwright's `browser.new_context(storage_state=...)` applies cookies at
    context creation but its per-origin localStorage restoration races the
    Angular SPA boot — the router evaluates auth guards before localStorage
    finishes hydrating, so the app redirects to /login even when a valid JWT
    is in the state file. Mirrors the working pattern in
    `persona_switch_node._perform_auth_switch`:

      1. Navigate to target_url (cookies already applied).
      2. Manually inject localStorage entries via page.evaluate.
      3. Reload so Angular's initial route resolution sees the JWT.
      4. Verify the JWT is now present in localStorage.

    Raises RuntimeError if the JWT is missing after the reload — that's an
    unambiguous signal the role's cached state is stale and should be refreshed
    (invalidate_role_state + retry, or fall back to a form-fill login).
    """
    jwt_key = "vc2JWT"
    try:
        from backend.profiles import get_active_profile as _gap
        _profile = _gap()
        if _profile and getattr(_profile, "jwt_storage_key", None):
            jwt_key = _profile.jwt_storage_key
    except Exception:
        pass

    # Initial navigation — cookies are already applied by the context.
    # Use domcontentloaded, not networkidle, because Angular dev-server URLs
    # (localhost:4200) never reach networkidle (HMR WebSocket).
    try:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
    except Exception as nav_err:
        logger.warning("[%s] CU: role-auth initial nav non-fatal: %s", run_id, nav_err)

    # Inject localStorage entries from the state file for any origin that
    # matches the target URL host (handles trailing-slash variance).
    try:
        with open(storage_state_path) as f:
            state_data = json.load(f)
    except Exception as e:
        raise RuntimeError(f"failed to read storage state {storage_state_path}: {e}") from e

    injected = 0
    for origin in state_data.get("origins", []):
        origin_url = (origin.get("origin") or "").rstrip("/")
        if not origin_url:
            continue
        if origin_url not in target_url and target_url.rstrip("/") not in origin_url:
            continue
        for item in origin.get("localStorage", []):
            name = item.get("name") or item.get("key")
            value = item.get("value")
            if name is None or value is None:
                continue
            try:
                await page.evaluate(
                    f"localStorage.setItem({json.dumps(name)}, {json.dumps(value)})"
                )
                injected += 1
            except Exception as ls_err:
                logger.debug("[%s] localStorage inject skipped: %s", run_id, ls_err)

    logger.info(
        "[%s] CU: role-auth injected %d localStorage entries — reloading to let Angular re-read",
        run_id, injected,
    )

    # Reload so Angular's router sees the JWT on initial route resolution.
    # domcontentloaded (not networkidle) for the same reason as above.
    try:
        await page.reload(wait_until="domcontentloaded", timeout=30_000)
    except Exception as reload_err:
        logger.warning("[%s] CU: role-auth reload non-fatal: %s", run_id, reload_err)
    # Small settle delay so Angular's initial route guard has a tick to read
    # localStorage and (if authenticated) render the dashboard shell.
    try:
        await page.wait_for_timeout(1500)
    except Exception:
        pass

    # Verify — if we're still on /login or JWT is absent, the cached state is
    # stale. Surface that explicitly.
    try:
        jwt_value = await page.evaluate(f"localStorage.getItem('{jwt_key}')")
    except Exception:
        jwt_value = None
    current_url = (page.url or "").lower()
    off_login = "/login" not in current_url and "/auth" not in current_url and current_url != "about:blank"
    has_auth_cookie = False
    try:
        cookies = await page.context.cookies()
        has_auth_cookie = any(
            any(k in c.get("name", "").lower() for k in ["ssojwt", "vc2jwt", "vcreative_session", "ppo_session"])
            or (off_login and any(k in c.get("name", "").lower() for k in ["session", "token"]))
            for c in cookies
        )
    except Exception:
        pass

    auth_verified = (bool(jwt_value) or has_auth_cookie) and off_login
    if not auth_verified:
        raise RuntimeError(
            f"role authentication verification failed: "
            f"jwt_present={bool(jwt_value)}, has_auth_cookie={has_auth_cookie}, url={current_url}. "
            f"Cached storage state may be stale — try invalidating it and re-running."
        )
    logger.info(
        "[%s] CU: role auth verified (jwt_present=%s, auth_cookie=%s, url=%s)",
        run_id, bool(jwt_value), has_auth_cookie, current_url,
    )


async def _do_ghost_login(
    page,
    run_id: str,
    target_url: str,
    admin_email: str,
    admin_password: str,
) -> None:
    """
    Authenticate as Admin. This IS the same primitive the existing
    ghost_login_node uses — imported directly, no code duplication.
    The ghost-panel DOM interaction (clicking the picker, selecting the
    target user) is left to the Computer-Use loop, exactly like the
    existing node leaves it to the planner.
    """
    from backend.engine.ghost_login_node import _resolve_ghost_login_url
    from backend.engine.persona_switch_node import (
        _ghost_creds,
        _login_with_ephemeral_creds,
        _wait_for_post_login_spa_render,
    )

    # Prime the credential cache so any downstream HITL gate sees them.
    _ghost_creds[run_id] = {"email": admin_email, "password": admin_password}

    ghost_login_url = _resolve_ghost_login_url(target_url)
    logger.info(
        "[%s] CU: authenticating at %s — email=%s, password=%s",
        run_id, ghost_login_url,
        admin_email or "<EMPTY>",
        "<set>" if admin_password else "<EMPTY>",
    )

    result = await _login_with_ephemeral_creds(
        page, admin_email, admin_password, ghost_login_url, run_id
    )
    if not result.get("success"):
        raise RuntimeError(f"admin authentication failed: {result}")

    # For products with a separate login site (vPromotions, vPPO), navigate
    # to the product URL now — the SSO cookie carries the session.
    if ghost_login_url.rstrip("/") != target_url.rstrip("/"):
        logger.info("[%s] CU: navigating to product URL: %s", run_id, target_url)
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
            await _wait_for_post_login_spa_render(page, run_id)
        except Exception as nav_err:
            logger.warning("[%s] CU: product nav non-fatal error: %s", run_id, nav_err)


# ---------------------------------------------------------------------------
# HITL fallback
# ---------------------------------------------------------------------------


async def _hitl_takeover(run_id: str, reason: str) -> str:
    """Trigger the existing HITL takeover flow and wait for the human to finish."""
    from backend.engine.human_takeover import register_takeover, _takeover_data
    event = register_takeover(run_id)
    logger.warning("[%s] CU: HITL takeover requested — reason=%s", run_id, reason[:200])
    await event.wait()
    explanation = (_takeover_data.get(run_id) or {}).get("explanation", "") if _takeover_data else ""
    logger.info("[%s] CU: HITL takeover done — explanation=%s", run_id, explanation[:200])
    return explanation


# ---------------------------------------------------------------------------
# Transcript persistence
# ---------------------------------------------------------------------------


def _transcript_dir(run_id: str) -> Path:
    d = Path(os.environ.get("VQA_CU_TRANSCRIPT_DIR", ".logs/computer_use")) / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_transcript(run_id: str, iter_idx: int, kind: str, payload: Any) -> None:
    """Best-effort transcript persistence — never raises."""
    try:
        path = _transcript_dir(run_id) / f"{iter_idx:03d}_{kind}.json"
        # Strip image bytes from persisted payload to keep files small — write
        # separate .png files for images instead.
        def _redact(o):
            if isinstance(o, dict):
                out = {}
                for k, v in o.items():
                    if k == "bytes" and isinstance(v, (bytes, bytearray)):
                        out[k] = f"<{len(v)} bytes>"
                    else:
                        out[k] = _redact(v)
                return out
            if isinstance(o, list):
                return [_redact(x) for x in o]
            return o
        path.write_text(json.dumps(_redact(payload), indent=2, default=str))
    except Exception as e:
        logger.debug("[%s] transcript write skipped: %s", run_id, e)


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------
#
# POST /api/run/<run_id>/cancel adds run_id to backend.api.routes._cancelled_runs.
# The legacy astream loop checks this in-loop; the CU loop must do the same or
# the "Stop Test" button in the UI has no effect until the browser closes for
# some other reason (usually the user closing the window manually), at which
# point Playwright raises TargetClosedError and the run reports status=error
# instead of status=cancelled.


def _is_cancelled(run_id: str) -> bool:
    """
    Check whether the operator has requested cancellation via POST
    /api/run/<run_id>/cancel. Lazy-imports the routes-owned set to avoid
    a circular dep. Returns False on any import/lookup failure — a cancel
    signal that can't be read is safer as 'keep running' than as 'stop'.
    """
    try:
        from backend.api.routes import _cancelled_runs  # noqa: PLC0415
        return run_id in _cancelled_runs
    except Exception:
        return False


def _discard_cancel(run_id: str) -> None:
    """Clear the cancel signal after honoring it (matches legacy behavior)."""
    try:
        from backend.api.routes import _cancelled_runs  # noqa: PLC0415
        _cancelled_runs.discard(run_id)
    except Exception:
        pass


# Playwright errors that mean 'the browser or page went away' and should
# terminate the loop cleanly rather than surfacing as status=error.
_BROWSER_GONE_MARKERS = (
    "target closed",
    "browser has been closed",
    "context was destroyed",
    "connection closed",
)


def _is_browser_gone(exc: BaseException) -> bool:
    """Match browser-closed errors by message so we catch every Playwright
    variant (TargetClosedError, Error('Target page, context or browser has
    been closed'), sync-vs-async divergence, etc.)."""
    msg = str(exc).lower()
    return any(m in msg for m in _BROWSER_GONE_MARKERS)


# ---------------------------------------------------------------------------
# AC step progress broadcasting
# ---------------------------------------------------------------------------
#
# The frontend Copilot sidebar renders every AC step with a status pill.
# Without ac_progress WebSocket messages, every step stays "pending" (rendered
# as "Waiting" in the UI) even after the loop drives the browser through them.
# Two paths write to this state:
#   1. Lifecycle broadcasts (run start / done / terminal error) — a safety net
#      so the UI always advances SOMETHING even if the model never marks steps.
#   2. Model-driven `mark_step_status` tool calls — the fine-grained path.
#
# Everything below is defensive: broadcast failures never crash the loop.


def _init_step_state(steps: list[str] | None) -> list[dict]:
    """
    Materialize the step state that the WS side will replay verbatim.

    Dedupes by normalized text (case-insensitive, whitespace-collapsed),
    preserving first-occurrence order. The AC parser legitimately emits
    the same setup steps ("Authenticate…", "Click New PRF", "Click Save")
    across multiple test scenarios — collapsing them keeps the UI list
    from ballooning to 50+ near-identical rows while the model still sees
    the full AC text in the user message and can execute every scenario.

    Indices are re-numbered contiguously after dedupe so the model's
    `mark_step_status(index=N)` calls line up with the row positions the
    frontend renders.
    """
    if not steps:
        return []
    seen: set[str] = set()
    out: list[dict] = []
    for raw in steps:
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if not text:
            continue
        norm = " ".join(text.lower().split())
        if norm in seen:
            continue
        seen.add(norm)
        is_ghost, ghost_target = _parse_ghost_target(text)
        out.append({
            "index": len(out),
            "text": text,
            "status": "pending",
            "error": "",
            "human_selector": "",
            # Ghost-login rail metadata. `is_ghost_step` gates the runner-side
            # persona-badge check when the model marks this step passed;
            # `ghost_target` is the parsed "as X" name (None if not named).
            "is_ghost_step": is_ghost,
            "ghost_target": ghost_target,
        })
    return out


async def _broadcast_step_state(run_id: str, state: list[dict]) -> None:
    """Send the full step list to any connected WS clients. Best-effort."""
    if not state:
        return
    try:
        from backend.api.routes import _broadcast_ac_progress  # noqa: PLC0415
        await _broadcast_ac_progress(run_id, state)
    except Exception as e:
        logger.debug("[%s] ac_progress broadcast skipped: %s", run_id, e)


def _apply_step_update(state: list[dict], index: int, status: str, note: str = "") -> bool:
    """
    Apply a single step-status update in place. Returns True if the state
    actually changed (so the caller can skip a redundant broadcast).
    """
    if not state or not (0 <= index < len(state)):
        return False
    cur = state[index]
    new_error = note if status == "failed" else cur.get("error", "")
    if cur.get("status") == status and cur.get("error", "") == new_error:
        return False
    cur["status"] = status
    cur["error"] = new_error
    return True


def _finalize_step_state(state: list[dict], terminal_status: str) -> None:
    """
    Lifecycle safety net: on terminal states, ensure the step list reflects
    something reasonable so the UI never sits on a stale in_progress row.

    - "done"                     → any non-terminal step becomes passed
    - "help" / "timeout" / "cap" → in_progress becomes failed, remaining stay pending
    - "error"                    → in_progress becomes failed
    """
    if not state:
        return
    terminal_set = {"passed", "failed", "skipped"}
    if terminal_status == "done":
        for s in state:
            if s.get("status") not in terminal_set:
                s["status"] = "passed"
                s["error"] = ""
        return
    # Non-success terminals
    for s in state:
        if s.get("status") == "in_progress":
            s["status"] = "failed"
            if not s.get("error"):
                s["error"] = f"run ended with status={terminal_status}"


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def run_computer_use(
    ticket_id: str,
    target_url: str,
    admin_email: str,
    admin_password: str,
    product: str | None = None,
    run_id: str | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_wall_seconds: int = DEFAULT_MAX_WALL_SECONDS,
    max_usd: float = DEFAULT_MAX_USD,
    keep_screenshots: int = DEFAULT_KEEP_SCREENSHOTS,
    prune_batch: int = DEFAULT_PRUNE_BATCH,
    stuck_iterations_threshold: int = DEFAULT_STUCK_ITERATIONS_THRESHOLD,
    widget_hammer_window: int = DEFAULT_WIDGET_HAMMER_WINDOW,
    widget_hammer_threshold: int = DEFAULT_WIDGET_HAMMER_THRESHOLD,
    steps: list[str] | None = None,
    user_role: str | None = None,
) -> dict[str, Any]:
    """
    Drive a Jira ticket's AC to completion using a screenshot → LLM → tool loop.

    Returns a summary dict — includes run_id, terminal_status ("done" |
    "help" | "timeout" | "cap" | "cost_cap" | "error"), final_summary,
    iterations, cost totals, and a path to the video recording (if the
    browser closed cleanly).
    """
    run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
    model_id = _model_id()
    prices = _pricing_for(model_id)

    logger.info(
        "[%s] CU: starting Computer-Use loop — ticket=%s product=%s model=%s "
        "max_usd=$%.2f keep_screenshots=%d prune_batch=%d stuck_threshold=%d",
        run_id, ticket_id, product, model_id, max_usd, keep_screenshots,
        prune_batch, stuck_iterations_threshold,
    )

    # 1. Jira ticket. JiraTicketContext is a TypedDict — access via dict indexing.
    # The client already applies "AC → description" fallback into acceptance_criteria,
    # so reading that field is enough; description is kept as a belt-and-suspenders
    # fallback in case the client's field packing changes.
    ticket = await fetch_ticket_context(ticket_id)
    ac_text = (ticket.get("acceptance_criteria") or ticket.get("description") or "").strip()
    if not ac_text:
        raise ValueError(f"ticket {ticket_id} has neither AC nor description")

    # 2. Browser + video recording.
    #
    # If the caller supplied a `user_role` and no explicit admin creds override
    # is in play, use `ensure_role_authenticated(role)` to obtain a valid
    # Playwright storage-state and open the browser already-authenticated.
    # This is the same login helper used by web_surfer and switch_actor —
    # it handles TTL caching, refresh, and the actual login mechanics via
    # AuthManager, and takes credentials from the role registry (KB → env
    # → profile fallback).
    #
    # When explicit admin creds ARE supplied (Ghost Login admin, Custom
    # Credentials), we skip role auth and fall through to the manual
    # form-fill in _do_ghost_login so those creds actually get used.
    storage_state_path: str | None = None
    use_role_auth = bool(user_role) and not admin_email
    if use_role_auth:
        try:
            from backend.engine.auth_manager import ensure_role_authenticated

            storage_state_path = await asyncio.to_thread(
                ensure_role_authenticated, user_role, login_url=target_url
            )
            logger.info(
                "[%s] CU: role auth prepared for '%s' → storage_state=%s",
                run_id, user_role, storage_state_path,
            )
        except Exception as e:
            logger.error(
                "[%s] CU: ensure_role_authenticated('%s') failed: %s",
                run_id, user_role, e,
            )
            raise RuntimeError(
                f"role login failed for '{user_role}': {e}. "
                f"Check that ROLE_EMAIL_{user_role.upper()} and ROLE_DEFAULT_PASSWORD "
                f"are set correctly."
            ) from e

    manager = BrowserManager(run_id=run_id)
    page = await manager.start(storage_state=storage_state_path)
    register_manager(run_id, manager)

    result: dict[str, Any] = {
        "run_id": run_id,
        "ticket_id": ticket_id,
        "product": product,
        "model_id": model_id,
        "iterations": 0,
        "terminal_status": "error",
        "final_summary": "",
        "video_path": None,
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "max_usd": max_usd,
        "step_state": [],
        "stuck_reason": "",
    }

    # Snapshot the step list into WS-broadcast shape (never mutated by caller).
    step_state = _init_step_state(steps)

    try:
        # 3. Navigate + login
        if use_role_auth:
            # Playwright's context storage_state applies cookies reliably but
            # its localStorage restoration races Angular boot in this SPA
            # (proven pattern in _perform_auth_switch): we must manually inject
            # localStorage entries via page.evaluate AFTER navigation, then
            # reload so Angular reads them before the router runs.
            try:
                await _apply_role_storage_state(
                    page, run_id, target_url, storage_state_path,
                )
            except RuntimeError as role_auth_err:
                # Cached storage state is stale (JWT expired, session revoked).
                # Invalidate and retry — ensure_role_authenticated will re-login
                # via AuthManager and produce fresh state.
                logger.warning(
                    "[%s] CU: role auth verification failed (%s) — invalidating cache and retrying",
                    run_id, role_auth_err,
                )
                from backend.engine.auth_manager import invalidate_role_state
                await asyncio.to_thread(invalidate_role_state, user_role)
                from backend.engine.auth_manager import ensure_role_authenticated as _era
                storage_state_path = await asyncio.to_thread(_era, user_role, login_url=target_url)
                # Reapply cookies from the freshly-written state file
                with open(storage_state_path) as _f:
                    _fresh_state = json.load(_f)
                if _fresh_state.get("cookies"):
                    await page.context.add_cookies(_fresh_state["cookies"])
                await _apply_role_storage_state(
                    page, run_id, target_url, storage_state_path,
                )
        else:
            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
            except Exception as nav_err:
                logger.warning("[%s] CU: initial nav non-fatal: %s", run_id, nav_err)
            await _do_ghost_login(page, run_id, target_url, admin_email, admin_password)

        # 3.5 Initial step-state broadcast — mark step 0 as in_progress so the
        # UI immediately shows progression from "Waiting" once the loop starts.
        if step_state:
            _apply_step_update(step_state, 0, "in_progress")
            await _broadcast_step_state(run_id, step_state)

        # 4. Initial screenshot + first Claude call
        client = _get_bedrock_client()
        png = await _screenshot_png_bytes(page)
        # The model must see the SAME numbered list the runner tracks — pass
        # the dedupe'd texts pulled off step_state, not the raw `steps` input.
        dedupe_texts = [s["text"] for s in step_state] if step_state else None
        user_text = build_user_message(ac_text, target_url, ticket_id, steps=dedupe_texts)
        messages: list[dict] = [_initial_user_message(user_text, png)]
        _write_transcript(run_id, 0, "initial_user", {"text": user_text})

        # 5. Loop
        t_start = time.monotonic()
        # Runtime backpressure counters. See the constants block above for
        # the rationale — each detector counts consecutive turns matching
        # one anti-pattern and warns once its threshold is reached.
        # Observed on QA-359 run-55f70989:
        #   - wait_only:       spinner-poke loops
        #   - scroll_click_at: repeated click_at(1274,~650) on drawer edge
        #   - restart_intent:  model articulates "restart form", about to
        #                      throw away $5-10 of prior fills
        consecutive_wait_only_turns = 0
        consecutive_scroll_click_turns = 0
        consecutive_restart_intent_turns = 0
        consecutive_fill_fail_turns = 0
        # Stuck-iteration guardrail (dual signal). We track the iteration
        # index of the most recent progress event of EITHER type:
        #   (a) step_state change — bumps last_step_progress_iter
        #   (b) novel action within the current in_progress step —
        #       bumps last_novel_action_iter
        # When min(i - last_step_progress_iter, i - last_novel_action_iter)
        # crosses ``stuck_iterations_threshold``, we bail. See
        # ``DEFAULT_STUCK_ITERATIONS_THRESHOLD`` for the QA-359 rationale
        # behind the two signals (form-fill vs bounce-loop).
        #
        # ``seen_action_sigs`` holds (tool, canonical_target) signatures
        # for the current step. Cleared on every successful step_state
        # update so each step gets a fresh set; without the reset, sigs
        # from the previous step (e.g. clicks on the datepicker) would
        # spuriously suppress novelty on the next step.
        last_step_progress_iter = 0
        last_novel_action_iter = 0
        seen_action_sigs: set[tuple[str, Any]] = set()
        # Rolling window of the most recent widget keys (see `_widget_keys`).
        # When the same widget accounts for >= widget_hammer_threshold of the
        # last widget_hammer_window widget-locked calls, the loop bails with
        # terminal_status="stuck". Independent of the coarser stuck-iteration
        # cursor: it fires even when the model is marking other steps in
        # parallel, which is the exact failure mode we observed on QA-359
        # (60 iters spent on Copy-PRF → Save while marking step 19/20 passed).
        recent_widget_keys: list[str] = []
        for i in range(1, max_iterations + 1):
            if time.monotonic() - t_start > max_wall_seconds:
                logger.warning("[%s] CU: wall-clock cap reached at iter %d", run_id, i)
                result["terminal_status"] = "timeout"
                break

            # Honor operator cancellation. Checked once per iteration — same
            # cadence as the legacy astream loop at routes.py:705.
            if _is_cancelled(run_id):
                logger.info("[%s] CU: cancellation detected at iter %d — stopping", run_id, i)
                _discard_cancel(run_id)
                result["terminal_status"] = "cancelled"
                break

            # Stuck-iteration guardrail (dual signal): if neither the
            # step_state has changed NOR a novel action has been attempted
            # for ``stuck_iterations_threshold`` iterations, bail. Checked
            # BEFORE the Bedrock call so we don't pay for another turn we
            # already decided to abandon. Progress on EITHER axis resets
            # the counter — a run filling 15 form fields in a single step
            # keeps advancing via novelty even if no mark_step_status
            # lands. See ``DEFAULT_STUCK_ITERATIONS_THRESHOLD``.
            last_progress_iter = max(last_step_progress_iter, last_novel_action_iter)
            stuck_span = i - last_progress_iter
            if step_state and stuck_span >= stuck_iterations_threshold:
                logger.warning(
                    "[%s] CU: stuck-iteration cap reached at iter %d — "
                    "no step_state change AND no novel action in %d iterations "
                    "(threshold=%d). Terminating to prevent further runaway spend.",
                    run_id, i, stuck_span, stuck_iterations_threshold,
                )
                result["terminal_status"] = "stuck"
                result["iterations"] = i - 1  # last productive iter
                break

            # Batched pruning: mutates old image blocks only when total >
            # keep + prune_batch. Between events the message-token sequence
            # is STABLE, which is a hard co-requirement for the rolling
            # cache breakpoint below — an eager prune-every-iter policy
            # would mutate a message in the middle of the cached prefix and
            # collapse the cache_read benefit back to zero.
            _prune_old_screenshots(messages, keep_screenshots, prune_batch)

            # Rolling cache breakpoint: mark the tail user turn so this call
            # reads all prior turns from cache (~1/10 the input price) and
            # only pays uncached for the new assistant + tool_result delta
            # that follows. See ``_refresh_rolling_cache_point`` docstring
            # for the full mechanics + how it stacks with the two static
            # breakpoints (system prompt, initial user text).
            _refresh_rolling_cache_point(messages)

            response = await _call_bedrock(client, model_id, messages, SYSTEM_PROMPT)
            _write_transcript(run_id, i, "assistant", response.get("output", {}))

            # Accounting: capture Bedrock usage, price it, accumulate.
            usage = response.get("usage") or {}
            call_cost = _call_cost_usd(usage, prices)
            result["cost_usd"] += call_cost
            result["input_tokens"] += int(usage.get("inputTokens", 0) or 0)
            result["output_tokens"] += int(usage.get("outputTokens", 0) or 0)
            result["cache_read_tokens"] += int(usage.get("cacheReadInputTokens", 0) or 0)
            result["cache_write_tokens"] += int(usage.get("cacheWriteInputTokens", 0) or 0)

            tool_calls, text_response = _extract_tool_uses(response)

            # Append the assistant turn to the message history verbatim.
            # This preserves reasoningContent + every toolUse block Bedrock
            # sent — required so the next-turn toolResult IDs match up.
            assistant_content = response.get("output", {}).get("message", {}).get("content", [])
            messages.append({"role": "assistant", "content": assistant_content})

            # USD cap enforcement — after the call so we bill the current
            # call but stop before firing another.
            if result["cost_usd"] >= max_usd:
                logger.error(
                    "[%s] CU: USD cap hit at iter %d — cost=$%.4f cap=$%.2f. "
                    "Stopping run to prevent further spend. Raise VQA_CU_MAX_USD to allow more.",
                    run_id, i, result["cost_usd"], max_usd,
                )
                result["terminal_status"] = "cost_cap"
                result["iterations"] = i
                break

            if not tool_calls:
                # Model returned only text — nudge back to tool use.
                logger.warning(
                    "[%s] CU iter %d: model returned no tool call. Text=%r",
                    run_id, i, text_response[:200],
                )
                messages.append({
                    "role": "user",
                    "content": [{"text": "You must call exactly one tool per turn. Look at the screenshot and choose your next action."}],
                })
                # A no-tool turn is not a "wait" turn, but it's also not
                # forward progress — reset the wait counter so a stuck
                # model doesn't accidentally clear it by returning text
                # once between waits.
                continue

            # Novel-action tracking: any tool call whose (name, canonical
            # target) signature has NOT been seen yet in the current step
            # counts as forward progress and resets the stuck cursor. Non-
            # progress tools (wait, mark_step_status, done, request_help)
            # yield no signature and are ignored here — their accounting
            # runs elsewhere.
            for sig in _tool_call_signatures(tool_calls):
                if sig not in seen_action_sigs:
                    seen_action_sigs.add(sig)
                    last_novel_action_iter = i

            # Widget-hammer detection. Append this turn's widget-locked keys
            # to the rolling window, trim to `widget_hammer_window`, and bail
            # if any single widget accounts for >= widget_hammer_threshold of
            # the window. See `_widget_keys` for what counts as a widget.
            for wk in _widget_keys(tool_calls):
                recent_widget_keys.append(wk)
            if len(recent_widget_keys) > widget_hammer_window:
                recent_widget_keys = recent_widget_keys[-widget_hammer_window:]
            if len(recent_widget_keys) >= widget_hammer_threshold:
                top_key = max(set(recent_widget_keys), key=recent_widget_keys.count)
                top_hits = recent_widget_keys.count(top_key)
                if top_hits >= widget_hammer_threshold:
                    logger.warning(
                        "[%s] CU: widget-hammer cap reached at iter %d — "
                        "widget %r hit %d/%d times in the recent window "
                        "(threshold=%d). Terminating to prevent further "
                        "runaway spend on a single unresponsive/unavailable "
                        "target.",
                        run_id, i, top_key, top_hits, len(recent_widget_keys),
                        widget_hammer_threshold,
                    )
                    result["terminal_status"] = "stuck"
                    result["stuck_reason"] = (
                        f"widget-hammer: {top_key} hit {top_hits}× "
                        f"in last {len(recent_widget_keys)} turns"
                    )
                    result["iterations"] = i
                    break

            # Classify the turn and update the backpressure counters.
            # Each counter tracks its own anti-pattern independently and
            # resets on any turn that doesn't match. Any productive tool
            # (click, fill, press, mark_step_status, done, request_help)
            # breaks all counters naturally.
            if _is_wait_only_turn(tool_calls):
                consecutive_wait_only_turns += 1
            else:
                consecutive_wait_only_turns = 0
            if _is_scroll_click_turn(tool_calls):
                consecutive_scroll_click_turns += 1
            else:
                consecutive_scroll_click_turns = 0
            if _has_restart_intent(tool_calls):
                consecutive_restart_intent_turns += 1
            else:
                consecutive_restart_intent_turns = 0

            # Log the usage + cost line ONCE per Bedrock call (not per tool),
            # naming every tool the model requested for this turn.
            tool_summary = ",".join(c["name"] or "?" for c in tool_calls)
            logger.info(
                "[%s] CU iter %d: tools=[%s] (n=%d) | usage(in=%d out=%d cache_r=%d cache_w=%d) | +$%.4f (total: $%.4f / $%.2f cap)",
                run_id, i, tool_summary, len(tool_calls),
                int(usage.get("inputTokens", 0) or 0),
                int(usage.get("outputTokens", 0) or 0),
                int(usage.get("cacheReadInputTokens", 0) or 0),
                int(usage.get("cacheWriteInputTokens", 0) or 0),
                call_cost, result["cost_usd"], max_usd,
            )

            # Dispatch every tool call in the turn. Bedrock validates that the
            # NEXT user message carries a toolResult for EVERY toolUse in this
            # assistant turn — missing one raises ValidationException.
            #
            # Terminal actions (done, help) short-circuit differently:
            #   - done: dispatch all tools first (to satisfy caller intent),
            #     then break AFTER the loop without appending a toolResult
            #     turn (we're ending; no next request will be made)
            #   - help: dispatch all tools, take screenshot, run HITL, then
            #     append a single user turn with toolResults for all tools —
            #     the help tool's result is replaced with the human's
            #     explanation so the model has context to continue
            tool_results: list[tuple[str, str]] = []
            done_summary: str | None = None
            help_reason: str | None = None
            help_tool_id: str | None = None

            for call in tool_calls:
                call_name = call["name"] or ""
                call_id = call["id"] or f"no-id-{i}-{len(tool_results)}"
                call_input = call["input"] or {}

                logger.info(
                    "[%s] CU iter %d: tool=%s input=%s",
                    run_id, i, call_name, json.dumps(call_input)[:200],
                )

                status, result_text = await dispatch_tool(page, call_name, call_input)

                # Drain step-status update per tool call — mark_step_status
                # tools stage their update on page._vqa_ac_update.
                pending_update = getattr(page, "_vqa_ac_update", None)
                ghost_rejected = False
                if pending_update:
                    try:
                        page._vqa_ac_update = None
                    except Exception:
                        pass
                    pu_index = int(pending_update.get("index", -1))
                    pu_status = str(pending_update.get("status", ""))
                    pu_note = str(pending_update.get("note", ""))

                    # Ghost-login rail: if the model is trying to mark a
                    # ghost-login step passed/skipped, independently verify
                    # the top-right persona badge before letting the update
                    # land. Rejection rewrites the tool_result AND appends
                    # a warning so the model reads it inline with the next
                    # screenshot. See the "Ghost-login enforcement" section
                    # above for the failure mode this catches.
                    if (
                        step_state
                        and 0 <= pu_index < len(step_state)
                        and step_state[pu_index].get("is_ghost_step")
                        and pu_status in ("passed", "skipped")
                    ):
                        verified, badge_seen, target = await _verify_ghost_switch(
                            page,
                            step_state[pu_index].get("text", ""),
                            admin_email,
                        )
                        if not verified:
                            ghost_rejected = True
                            logger.warning(
                                "[%s] CU iter %d: REJECTING mark_step_status(index=%d, status=%s) "
                                "on ghost-login step — top-right badge %r does not reflect switch "
                                "to target %r",
                                run_id, i, pu_index, pu_status, badge_seen[:200], target,
                            )
                            # Flip result text so the model sees the rejection
                            # as a tool error rather than a success.
                            result_text = (
                                f"error: mark_step_status(index={pu_index}, status={pu_status!r}) "
                                f"REJECTED by runner — this is a ghost-login step and the "
                                f"top-right persona badge does not show the target user "
                                f"({target!r}). Badge currently reads: {badge_seen[:200]!r}. "
                                f"Perform the ghost switch first, then re-mark."
                            )
                            # Force the step back to in_progress (do NOT apply
                            # the model's passed/skipped mark). Emit a state
                            # broadcast so the UI reverts too.
                            if _apply_step_update(step_state, pu_index, "in_progress", ""):
                                await _broadcast_step_state(run_id, step_state)
                            # Stash the rejection payload — the backpressure
                            # injector at the end of the turn appends a
                            # detailed remediation warning inline with the
                            # last tool_result the model will read next.
                            try:
                                page._vqa_ghost_reject_pending = {
                                    "index": pu_index,
                                    "status": pu_status,
                                    "step_text": step_state[pu_index].get("text", ""),
                                    "target": (
                                        target
                                        or step_state[pu_index].get("ghost_target")
                                        or "(no target named — must switch away from admin)"
                                    ),
                                    "badge": badge_seen,
                                }
                            except Exception:
                                pass

                    if not ghost_rejected and _apply_step_update(
                        step_state,
                        pu_index,
                        pu_status,
                        pu_note,
                    ):
                        # Forward progress — bump the stuck-iteration cursor
                        # so the guardrail at the top of the next iter sees a
                        # fresh budget. Ghost-reject reverts are intentionally
                        # NOT counted (they set the step BACK to in_progress).
                        last_step_progress_iter = i
                        # Clear novel-action memory: the new step gets a
                        # fresh signature set so sigs from the previous
                        # step (datepicker clicks, prior form fields)
                        # don't spuriously suppress novelty here. Also
                        # re-baseline last_novel_action_iter to now so
                        # the first action in the next step doesn't have
                        # to race the previous step's expired budget.
                        seen_action_sigs.clear()
                        last_novel_action_iter = i
                        await _broadcast_step_state(run_id, step_state)

                tool_results.append((call_id, result_text))

                if status == "done":
                    done_summary = result_text
                elif status == "help":
                    help_reason = result_text
                    help_tool_id = call_id

            # Fill-failure backpressure counter — must be updated AFTER
            # dispatch because we can't know from tool_calls alone whether
            # the fill will fail. Same reset-on-progress semantics as the
            # other counters: any turn without a fill error clears it.
            if _has_fill_error(tool_results):
                consecutive_fill_fail_turns += 1
            else:
                consecutive_fill_fail_turns = 0

            # Done: end the run. No toolResult turn appended — the loop is
            # ending, no further Bedrock call will happen.
            if done_summary is not None:
                logger.info("[%s] CU: model called done — summary=%r", run_id, done_summary[:200])
                result["terminal_status"] = "done"
                result["final_summary"] = done_summary
                result["iterations"] = i
                break

            # Auto-terminal safety net. If EVERY numbered AC step has been
            # marked passed by the model, the run is complete regardless
            # of whether the model called `done`. This catches the failure
            # mode observed on QA-359 where the model finished the AC but
            # kept driving into Edit-PRF / Copy-PRF flows and burned
            # ~$5-$7 past the terminal point. Only triggers when we HAVE
            # a step list — legacy no-steps runs still require an explicit
            # `done` call.
            if step_state and all(s.get("status") == "passed" for s in step_state):
                logger.info(
                    "[%s] CU: all %d AC steps marked passed — auto-terminal 'done' at iter %d",
                    run_id, len(step_state), i,
                )
                result["terminal_status"] = "done"
                result["final_summary"] = (
                    f"All {len(step_state)} AC steps marked passed by the model — "
                    "auto-terminal (model did not call `done` explicitly)."
                )
                result["iterations"] = i
                break

            # Screenshot for the next iteration's context.
            png = await _screenshot_png_bytes(page)
            try:
                (_transcript_dir(run_id) / f"{i:03d}_screenshot.png").write_bytes(png)
            except Exception:
                pass

            # Help: run HITL, replace the help tool's result with the human's
            # explanation so the model has context to continue.
            if help_reason is not None:
                logger.warning("[%s] CU: model called request_help — reason=%r", run_id, help_reason[:200])
                explanation = await _hitl_takeover(run_id, help_reason)
                tool_results = [
                    (tid, txt if tid != help_tool_id
                          else f"Human took over. Explanation: {explanation!r}. Continue from the current screenshot.")
                    for tid, txt in tool_results
                ]

            # Backpressure: append all triggered warnings to the LAST
            # toolResult text so the model reads them inline with the tool
            # output it's about to process. Multiple warnings can stack
            # in a single turn (e.g. scroll-click AND restart intent
            # together), which is the correct behavior — each anti-pattern
            # deserves its own callout.
            triggered_warnings: list[str] = []
            if consecutive_wait_only_turns >= _WAIT_BACKPRESSURE_THRESHOLD:
                triggered_warnings.append(
                    _WAIT_BACKPRESSURE_WARNING.format(count=consecutive_wait_only_turns)
                )
            if consecutive_scroll_click_turns >= _SCROLL_CLICK_BACKPRESSURE_THRESHOLD:
                triggered_warnings.append(
                    _SCROLL_CLICK_BACKPRESSURE_WARNING.format(count=consecutive_scroll_click_turns)
                )
            if consecutive_restart_intent_turns >= _RESTART_INTENT_THRESHOLD:
                triggered_warnings.append(_RESTART_INTENT_WARNING)
            if consecutive_fill_fail_turns >= _FILL_FAIL_BACKPRESSURE_THRESHOLD:
                triggered_warnings.append(
                    _FILL_FAIL_BACKPRESSURE_WARNING.format(count=consecutive_fill_fail_turns)
                )
            # Ghost-login rail: if we rejected a mark this turn, always
            # inject the explanatory warning so the model reads it inline
            # with the tool error we already surfaced in the tool_result.
            ghost_reject = getattr(page, "_vqa_ghost_reject_pending", None)
            if ghost_reject:
                try:
                    page._vqa_ghost_reject_pending = None
                except Exception:
                    pass
                triggered_warnings.append(
                    _GHOST_REJECT_WARNING.format(
                        status=ghost_reject.get("status", ""),
                        index=ghost_reject.get("index", -1),
                        step_text=ghost_reject.get("step_text", "")[:300],
                        target=ghost_reject.get("target", "(unknown)"),
                        badge=(ghost_reject.get("badge") or "")[:300],
                    )
                )
                logger.warning(
                    "[%s] CU iter %d: injecting ghost-login rejection warning "
                    "for step %d",
                    run_id, i, ghost_reject.get("index", -1),
                )
            if triggered_warnings and tool_results:
                logger.warning(
                    "[%s] CU iter %d: injecting backpressure warnings "
                    "(wait=%d scroll=%d restart=%d fill_fail=%d, n_warnings=%d)",
                    run_id, i,
                    consecutive_wait_only_turns,
                    consecutive_scroll_click_turns,
                    consecutive_restart_intent_turns,
                    consecutive_fill_fail_turns,
                    len(triggered_warnings),
                )
                last_id, last_txt = tool_results[-1]
                tool_results[-1] = (last_id, last_txt + "".join(triggered_warnings))

            # Persist the finalized tool_result payload (post-HITL, post-
            # backpressure) so the report renderer can show operators the
            # exact text the model reads next. Written BEFORE messages.append
            # so a crash on message construction still leaves the audit row.
            _write_transcript(
                run_id,
                i,
                "tool_result",
                [{"tool_use_id": cid, "text": txt} for cid, txt in tool_results],
            )

            # Append ONE user message carrying one toolResult per tool call,
            # with the fresh screenshot attached to the last toolResult.
            messages.append(_build_multi_tool_result_message(tool_results, png))
            result["iterations"] = i
        else:
            # Fell off the loop without break — hit iteration cap
            logger.warning("[%s] CU: iteration cap %d reached", run_id, max_iterations)
            result["terminal_status"] = "cap"

    except (PlaywrightError, PlaywrightTimeoutError) as e:
        # Playwright errors — split into two classes:
        #   1. Browser-gone: page/context/browser closed mid-run (user hit
        #      Stop; user closed the Chromium window; manager.close ran
        #      from another path). Terminal="cancelled". No stack trace.
        #   2. Anything else Playwright raised: real error.
        if _is_browser_gone(e):
            logger.info(
                "[%s] CU: browser closed mid-run — treating as cancelled (%s)",
                run_id, str(e).split("\n")[0][:200],
            )
            # If cancel was outstanding, honor it; otherwise still call it
            # cancelled since from the UI perspective the run ended cleanly.
            _discard_cancel(run_id)
            result["terminal_status"] = "cancelled"
        else:
            logger.exception("[%s] CU: loop failed — %s", run_id, e)
            result["terminal_status"] = "error"
            result["error"] = str(e)

    except Exception as e:
        logger.exception("[%s] CU: loop failed — %s", run_id, e)
        result["terminal_status"] = "error"
        result["error"] = str(e)

    finally:
        # Terminal step-state broadcast BEFORE closing the browser so the UI
        # sees the final statuses (all-passed on done; in_progress → failed
        # on cap/timeout/error) rather than a stale in_progress row.
        try:
            _finalize_step_state(step_state, result["terminal_status"])
            await _broadcast_step_state(run_id, step_state)
        except Exception as fin_err:
            logger.debug("[%s] terminal ac_progress broadcast skipped: %s", run_id, fin_err)

        try:
            video_path = await manager.close()
            if video_path:
                result["video_path"] = str(video_path)
        except Exception as close_err:
            logger.warning("[%s] CU: browser close error: %s", run_id, close_err)
        unregister_manager(run_id)

        # Snapshot final step_state into the result — the report renderer
        # reads it to build the per-step pass/fail table. Deep-copied via
        # dict(...) to avoid handing out references to the live list.
        result["step_state"] = [dict(s) for s in step_state]

    logger.info(
        "[%s] CU: run complete — status=%s iterations=%d cost=$%.4f "
        "tokens(in=%d out=%d cache_r=%d cache_w=%d) model=%s",
        run_id, result["terminal_status"], result["iterations"], result["cost_usd"],
        result["input_tokens"], result["output_tokens"],
        result["cache_read_tokens"], result["cache_write_tokens"],
        model_id,
    )
    return result
