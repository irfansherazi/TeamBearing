"""
HTML report renderer for the Computer-Use loop.

Two-section report:
  1. Summary — KPIs, terminal status banner, per-AC-step pass/fail table,
     session video player (when uploaded to S3).
  2. Audit trail — one collapsible block per Bedrock iteration, showing:
     - post-action screenshot (S3-hosted when uploaded, else base64)
     - the plain-English action ("Click at (742, 318)", "Type email…")
     - Claude's reasoning text
     - the tool_result the model saw next turn
     - an error badge when the tool_result looks like an error

The audit trail is read back from the on-disk transcript directory written
by the loop (`_transcript_dir(run_id)` in `runner.py`):

  {run_id}/000_initial_user.json         — first user message (AC text)
  {run_id}/{i:03d}_assistant.json        — Bedrock output for iter i
  {run_id}/{i:03d}_tool_result.json      — finalized tool_result for iter i
  {run_id}/{i:03d}_screenshot.png        — post-action screenshot for iter i

Rendering modes:
  - `screenshot_urls` provided (S3 map) → HTML references S3 URLs. Small file,
    works from any browser, uploads cost O(iters) requests once at end of run.
  - `screenshot_urls` omitted → screenshots embedded as base64 data URIs so
    the file is self-contained (used by local dev / when S3 upload fails).

If the transcript dir is missing or partial, the audit trail degrades to
whatever is available; the summary section always renders.

Called from `backend/api/routes.py::_execute_cu_run`.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_STATUS_BADGES = {
    "passed": ("✅", "#0a7c2f"),
    "failed": ("❌", "#c62828"),
    "skipped": ("⏭️", "#6b7280"),
    "in_progress": ("⚙️", "#c07f00"),
    "pending": ("⏳", "#6b7280"),
}

_TERMINAL_COLORS = {
    "done": "#0a7c2f",
    "cap": "#c07f00",
    "cost_cap": "#c07f00",
    "timeout": "#c07f00",
    "stuck": "#c62828",
    "cancelled": "#6b7280",
    "help": "#7c3aed",
    "error": "#c62828",
}

# Tool_result payloads whose text starts with (or contains near the front)
# one of these markers count as an error for the per-iteration badge.
_ERROR_MARKERS = ("error:", "❌", "failed:", "exception", "traceback")


def _esc(s: Any) -> str:
    """HTML-escape a value; None → empty string."""
    if s is None:
        return ""
    return html.escape(str(s))


def _fmt_usd(v: Any) -> str:
    try:
        return f"${float(v):.4f}"
    except (TypeError, ValueError):
        return "$0.0000"


def _fmt_int(v: Any) -> str:
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return "0"


def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _transcript_dir(run_id: str) -> Path | None:
    """Mirror of runner._transcript_dir, but read-only — don't create the dir
    from the report path. Returns None when the dir doesn't exist yet."""
    base = Path(os.environ.get("VQA_CU_TRANSCRIPT_DIR", ".logs/computer_use"))
    d = base / run_id
    return d if d.is_dir() else None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.debug("report: skip %s (%s)", path, e)
        return None


def _b64_png(path: Path) -> str:
    """PNG → base64 data URI. Empty string if the file is missing/unreadable."""
    try:
        raw = path.read_bytes()
        return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    except Exception as e:
        logger.debug("report: screenshot %s unreadable (%s)", path, e)
        return ""


def _extract_assistant(payload: Any) -> tuple[str, list[dict]]:
    """
    Pull reasoning text and tool calls out of a Bedrock Converse response.

    Returns (reasoning_text, [{tool_use_id, name, input}]). Handles both the
    raw response.output shape ({"message": {"role": ..., "content": [...]}})
    and the already-unwrapped message content array.
    """
    if not isinstance(payload, dict):
        return "", []
    msg = payload.get("message") or payload
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return "", []

    reasoning_parts: list[str] = []
    tool_calls: list[dict] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if "text" in block and isinstance(block["text"], str):
            reasoning_parts.append(block["text"])
        rc = block.get("reasoningContent")
        if isinstance(rc, dict):
            rt = rc.get("reasoningText")
            if isinstance(rt, dict):
                # Only the human-readable "text" field — never the opaque
                # base64 "signature" blob (it's noise in a UI report).
                t = rt.get("text")
                if isinstance(t, str) and t.strip():
                    reasoning_parts.append(t)
        tu = block.get("toolUse")
        if isinstance(tu, dict):
            tool_calls.append({
                "tool_use_id": tu.get("toolUseId", ""),
                "name": tu.get("name", ""),
                "input": tu.get("input", {}),
            })
    return "\n\n".join(p for p in reasoning_parts if p).strip(), tool_calls


def _looks_like_error(text: str) -> bool:
    if not text:
        return False
    low = text.strip().lower()
    return any(low.startswith(m) or m in low[:120] for m in _ERROR_MARKERS)


# ---------------------------------------------------------------------------
# Human-readable tool rendering
# ---------------------------------------------------------------------------
#
# The Bedrock tool_use blocks are exact JSON — legible if you know the
# schema, opaque if you don't. Operators reading a failure report want to
# read "Clicked at (742, 318)" not "{'x': 742, 'y': 318}". The mapping
# below converts each known tool's input into a one-line human sentence.
# Unknown tools fall through to a JSON pretty-print — nothing is dropped,
# only reformatted.


def _humanize_tool(name: str, tool_input: Any) -> str:
    """Render a tool call as a single human sentence. Never raises."""
    if not isinstance(tool_input, dict):
        return _esc(str(tool_input or ""))
    try:
        if name == "click_at":
            x, y = tool_input.get("x", "?"), tool_input.get("y", "?")
            desc = tool_input.get("description") or tool_input.get("target") or ""
            base = f"Click at pixel ({x}, {y})"
            return _esc(f"{base} — {desc}" if desc else base)
        if name in ("type_text", "type", "fill"):
            text = tool_input.get("text", tool_input.get("value", ""))
            target = tool_input.get("target") or tool_input.get("field") or ""
            preview = _truncate(str(text), 120)
            if target:
                return f'Type into <code>{_esc(target)}</code>: <code>{_esc(preview)}</code>'
            return f'Type: <code>{_esc(preview)}</code>'
        if name == "press":
            return f"Press key <code>{_esc(tool_input.get('key', '?'))}</code>"
        if name == "scroll":
            direction = tool_input.get("direction", "?")
            amount = tool_input.get("amount", "")
            return _esc(f"Scroll {direction}" + (f" by {amount}" if amount else ""))
        if name == "navigate":
            return f"Navigate to <code>{_esc(tool_input.get('url', ''))}</code>"
        if name == "wait":
            secs = tool_input.get("seconds", tool_input.get("duration_seconds", "?"))
            reason = tool_input.get("reason", "")
            base = f"Wait {secs}s"
            return _esc(f"{base} — {reason}" if reason else base)
        if name == "mark_step_status":
            idx = tool_input.get("index", "?")
            status = tool_input.get("status", "?")
            note = tool_input.get("note", "")
            base = f"Mark step {idx} as <strong>{_esc(status)}</strong>"
            return f"{base}{' — ' + _esc(note) if note else ''}"
        if name == "done":
            summary = tool_input.get("summary", tool_input.get("final_summary", ""))
            return f"Signal <strong>DONE</strong>: {_esc(_truncate(str(summary), 400))}"
        if name == "request_help":
            reason = tool_input.get("reason", "")
            return f"Request human help: {_esc(_truncate(str(reason), 400))}"
        if name == "ghost_login":
            target = tool_input.get("target") or tool_input.get("user") or ""
            return f"Ghost-login as <code>{_esc(target)}</code>"
    except Exception:
        pass
    # Unknown tool — best-effort compact JSON.
    try:
        return f"<code>{_esc(json.dumps(tool_input, default=str))}</code>"
    except Exception:
        return _esc(str(tool_input))


def _load_iterations(run_id: str) -> list[dict]:
    """
    Walk the transcript dir and return a list of iteration dicts, one per
    non-zero iteration index that has SOMETHING on disk. Missing pieces are
    OK — an iteration with only an assistant.json (crashed before tool
    dispatch) still renders.

    Also returns iteration 0 as a synthetic "initial user message" row so
    operators see the exact AC prompt at the top of the audit trail.
    """
    d = _transcript_dir(run_id)
    if d is None:
        return []

    idx_pattern = re.compile(r"^(\d{3})_(.+)\.(json|png)$")
    by_idx: dict[int, dict[str, Path]] = {}
    for p in d.iterdir():
        m = idx_pattern.match(p.name)
        if not m:
            continue
        idx = int(m.group(1))
        kind = m.group(2)
        by_idx.setdefault(idx, {})[kind] = p

    out: list[dict] = []
    for idx in sorted(by_idx):
        files = by_idx[idx]
        iter_data: dict[str, Any] = {"index": idx, "files": files}

        if idx == 0:
            initial = _read_json(files.get("initial_user")) if files.get("initial_user") else None
            if isinstance(initial, dict):
                iter_data["initial_user_text"] = initial.get("text", "")
            out.append(iter_data)
            continue

        assistant_payload = _read_json(files.get("assistant")) if files.get("assistant") else None
        reasoning, tool_calls = _extract_assistant(assistant_payload)
        iter_data["reasoning"] = reasoning
        iter_data["tool_calls"] = tool_calls

        tr_payload = _read_json(files.get("tool_result")) if files.get("tool_result") else None
        iter_data["tool_results"] = tr_payload if isinstance(tr_payload, list) else []

        iter_data["had_error"] = any(
            _looks_like_error(tr.get("text", "")) for tr in iter_data["tool_results"] if isinstance(tr, dict)
        )
        out.append(iter_data)

    return out


def _render_tool_call(tc: dict, outcome: dict | None) -> str:
    """
    Render one action the agent took, followed inline by its outcome.

    Pairing call+result on one row (instead of two separate "Actions" and
    "Outcomes" lists) is the biggest readability win for non-engineers —
    they see "agent clicked Save" and "Save succeeded" side-by-side rather
    than having to mentally join two lists by an opaque tool_use_id.

    `outcome` may be None when the loop broke before writing the tool_result
    file (done/all-passed exits). We still render the action row — the
    absence of an outcome pill is itself signal ("no result — run ended").

    The raw JSON input is kept behind a collapsed <details> for engineers
    who need to reproduce; product readers never see it unless they open it.
    """
    name = tc.get("name", "")
    tool_input = tc.get("input") or {}
    human = _humanize_tool(name, tool_input)
    try:
        input_json = json.dumps(tool_input, indent=2, default=str)
    except Exception:
        input_json = str(tool_input)

    outcome_html = ""
    if outcome is not None:
        text = (outcome.get("text") or "").strip()
        if _looks_like_error(text):
            outcome_html = (
                '<div class="outcome outcome-err">'
                f'<span class="outcome-pill err">✗ Error</span>'
                f'<pre class="outcome-text">{_esc(text)}</pre>'
                '</div>'
            )
        elif text:
            outcome_html = (
                '<div class="outcome outcome-ok">'
                '<span class="outcome-pill ok">✓ Success</span>'
                f'<pre class="outcome-text">{_esc(text)}</pre>'
                '</div>'
            )
        else:
            outcome_html = (
                '<div class="outcome outcome-ok">'
                '<span class="outcome-pill ok">✓ Success</span>'
                '</div>'
            )

    return (
        f'<div class="tool-call">'
        f'<div class="tool-human">{human}</div>'
        f'{outcome_html}'
        f'<details class="tool-raw"><summary>Technical details</summary>'
        f'<pre class="tool-input">{_esc(input_json)}</pre>'
        f'</details>'
        f'</div>'
    )


def _bookkeeping_summary(tool_calls: list[dict]) -> str:
    """
    Compact one-liner for iterations whose only actions are the agent
    marking AC-step progress. These are extremely common (an agent often
    marks 5 already-completed steps as passed in a single turn on startup)
    and rendering each as a full block drowns the product-readable
    activity log in identical rows.

    Groups the marks by status ("passed", "skipped", "failed") and lists
    the indices affected. Falls back to a generic phrase if the shape
    doesn't match.
    """
    by_status: dict[str, list[int]] = {}
    for tc in tool_calls:
        if tc.get("name") != "mark_step_status":
            continue
        ti = tc.get("input") or {}
        status = str(ti.get("status", "?"))
        try:
            idx = int(ti.get("index"))
        except (TypeError, ValueError):
            continue
        by_status.setdefault(status, []).append(idx)
    if not by_status:
        return "Reviewed test progress"
    bits: list[str] = []
    for status in ("passed", "failed", "skipped"):
        idxs = sorted(set(by_status.get(status, [])))
        if not idxs:
            continue
        label = "step" if len(idxs) == 1 else "steps"
        bits.append(f'marked AC {label} {", ".join(str(i) for i in idxs)} as <strong>{_esc(status)}</strong>')
    return "; ".join(bits) if bits else "Reviewed test progress"


def _render_iter_block(
    it: dict,
    *,
    screenshot_urls: dict[int, str] | None,
) -> str:
    """
    Render one turn of the agent — the atomic unit of the activity log.

    A "turn" is one Bedrock call: the agent looks at the screen, thinks,
    then dispatches one or more actions (usually one). We call it "Action N"
    in the UI because "iteration" is engineer jargon and "step" collides
    with the AC-step numbering the top of the report already uses.

    Layout inside each turn:
      - Post-action screenshot (what the browser looked like after)
      - Agent thinking (the plain-language reasoning Claude emitted)
      - Each action paired inline with its result (✓ Success / ✗ Error)

    Three special cases:
      1. idx=0 → "Test brief" row showing the raw AC prompt sent to the agent.
      2. All actions are mark_step_status → "bookkeeping" turn. Renders a
         one-line "marked AC steps X, Y, Z as passed" summary in the header
         and hides the noisy per-mark bodies. Keeps thinking + screenshot
         when expanded because the reasoning is often the interesting bit
         ("I see we're already logged in, so steps 0-4 are already done").
      3. Mixed (real actions + a few mark_step_status calls) → real actions
         render inline, the marks collapse into a small footer note.
    """
    idx = it["index"]

    # ── Turn 0: the AC prompt that kicked off the run ──────────────
    if idx == 0:
        prompt = _esc(it.get("initial_user_text", ""))
        if not prompt:
            return ""
        return (
            f'<details class="iter iter-kickoff" open>'
            f'<summary>'
            f'<span class="iter-num">Test brief</span>'
            f'<span class="iter-summary muted">what the agent was asked to do</span>'
            f'</summary>'
            f'<div class="iter-body">'
            f'<pre class="prompt-text">{prompt}</pre>'
            f'</div></details>'
        )

    reasoning = it.get("reasoning", "") or ""
    tool_calls = it.get("tool_calls", []) or []
    tool_results = it.get("tool_results", []) or []
    had_error = it.get("had_error", False)

    # Screenshot source: S3 URL if we have one for this turn, else base64.
    ss_src = ""
    if screenshot_urls and idx in screenshot_urls:
        ss_src = screenshot_urls[idx]
    else:
        ss_path = (it.get("files") or {}).get("screenshot")
        if ss_path:
            ss_src = _b64_png(ss_path)

    # Partition actions: real work vs. AC-step bookkeeping. mark_step_status
    # is the agent maintaining test-progress state; it's not something a
    # PM cares about seeing per-mark. Collapse them.
    real_calls = [tc for tc in tool_calls if tc.get("name") != "mark_step_status"]
    marks = [tc for tc in tool_calls if tc.get("name") == "mark_step_status"]
    bookkeeping_only = bool(marks) and not real_calls

    # Pair each tool call with its outcome by matching tool_use_id.
    outcomes_by_id: dict[str, dict] = {}
    for tr in tool_results:
        if isinstance(tr, dict):
            outcomes_by_id[tr.get("tool_use_id", "")] = tr

    # ── Header summary: what happened this turn, in one line ───────
    if bookkeeping_only:
        head_summary = f'<span class="iter-summary muted">{_bookkeeping_summary(marks)}</span>'
    elif real_calls:
        first_human = _humanize_tool(real_calls[0].get("name", "?"), real_calls[0].get("input") or {})
        extra_count = len(real_calls) - 1
        extra = f' <span class="muted">(+{extra_count} more)</span>' if extra_count > 0 else ""
        head_summary = f'<span class="iter-summary">{first_human}</span>{extra}'
    elif tool_calls:
        # No real calls, no marks — shouldn't happen, but be defensive.
        first_human = _humanize_tool(tool_calls[0].get("name", "?"), tool_calls[0].get("input") or {})
        head_summary = f'<span class="iter-summary">{first_human}</span>'
    else:
        head_summary = '<span class="muted">agent returned only text (no action taken)</span>'

    err_badge = '<span class="err-badge">Error</span>' if had_error else ""

    # ── Body sections ──────────────────────────────────────────────
    screenshot_html = ""
    if ss_src:
        screenshot_html = (
            '<div class="section-label">Screen after</div>'
            f'<img class="iter-screenshot" src="{ss_src}" loading="lazy" alt="Turn {idx} screenshot" />'
        )
    reasoning_html = ""
    if reasoning:
        reasoning_html = (
            '<div class="section-label">Agent thinking</div>'
            f'<pre class="reasoning">{_esc(reasoning)}</pre>'
        )
    actions_html = ""
    if real_calls:
        actions_html = (
            '<div class="section-label">What the agent did</div>'
            + "".join(
                _render_tool_call(tc, outcomes_by_id.get(tc.get("tool_use_id", "")))
                for tc in real_calls
            )
        )
    # Bookkeeping footer: only shown when there were ALSO real actions;
    # bookkeeping-only turns already surface this in the header.
    marks_footer_html = ""
    if marks and not bookkeeping_only:
        marks_footer_html = (
            '<div class="marks-footer">'
            f'<span class="marks-icon">🏷</span> Also {_bookkeeping_summary(marks)}'
            '</div>'
        )

    classes = "iter"
    if had_error:
        classes += " iter-error"
    if bookkeeping_only:
        classes += " iter-bookkeeping"

    return (
        f'<details class="{classes}">'
        f'<summary>'
        f'<span class="iter-num">Action {idx}</span>'
        f'{head_summary} {err_badge}'
        f'</summary>'
        f'<div class="iter-body">'
        f'{screenshot_html}'
        f'{reasoning_html}'
        f'{actions_html}'
        f'{marks_footer_html}'
        f'</div></details>'
    )


def _render_audit_trail(run_id: str, *, screenshot_urls: dict[int, str] | None) -> str:
    iters = _load_iterations(run_id) if run_id else []
    if not iters:
        return (
            '<div class="section">'
            '<h2>Activity log</h2>'
            '<p class="muted">No transcript files found for this run — '
            'the run may have crashed before writing anything, or the '
            'transcript directory was cleared.</p>'
            '</div>'
        )
    blocks = [_render_iter_block(it, screenshot_urls=screenshot_urls) for it in iters]
    blocks = [b for b in blocks if b]
    n_iters = sum(1 for it in iters if it["index"] > 0)
    n_errors = sum(1 for it in iters if it.get("had_error"))
    err_note = f' · <span class="err-badge">{n_errors} with errors</span>' if n_errors else ""
    return (
        '<div class="section">'
        f'<h2>Activity log <span class="section-count">({n_iters} agent actions{err_note})</span></h2>'
        '<p class="muted section-hint">Each row is one turn the agent took. Click any row to see what it saw on screen, what it was thinking, and the result.</p>'
        f'{"".join(blocks)}'
        '</div>'
    )


def _render_video(video_url: str) -> str:
    if not video_url:
        return ""
    esc_url = _esc(video_url)
    return (
        '<div class="section">'
        '<h2>Session recording</h2>'
        f'<video class="session-video" controls preload="metadata" src="{esc_url}">'
        f'Your browser cannot play this video. '
        f'<a href="{esc_url}">Download the .webm</a>.'
        '</video>'
        '</div>'
    )


def render_cu_report(
    result: dict[str, Any],
    *,
    screenshot_urls: dict[int, str] | None = None,
    video_url: str = "",
) -> str:
    """
    Render a self-contained HTML report from a `run_computer_use` result dict.

    Three sections:
      1. Summary — KPIs, terminal banner, per-AC-step pass/fail table.
         Uses only fields on the result dict; never touches disk.
      2. Session recording — embedded <video> when video_url is provided.
      3. Audit trail — per-iteration blocks (screenshot, reasoning, actions,
         outcomes) loaded from the on-disk transcript dir. Screenshots use
         S3 URLs when `screenshot_urls` is supplied (report stays small);
         otherwise base64 from disk (report becomes self-contained).

    Parameters
    ----------
    result : dict
        Expected keys: run_id, ticket_id, product, model_id, iterations,
        terminal_status, final_summary, stuck_reason (optional), cost_usd,
        input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
        max_usd, error, step_state, video_path. Missing keys render blank —
        the renderer never raises.
    screenshot_urls : dict[int, str] | None
        Optional map iter_idx → S3 URL. When provided, per-iter screenshots
        are rendered as ``<img src="{s3}">``. When None, screenshots are
        embedded as base64 from the transcript directory (matches the local
        dev / early-crash fallback).
    video_url : str
        Optional S3 URL of the session recording. When provided, renders a
        <video> player between the summary and audit sections.
    """
    run_id_raw = str(result.get("run_id", ""))
    run_id = _esc(run_id_raw)
    ticket_id = _esc(result.get("ticket_id", ""))
    product = _esc(result.get("product") or "—")
    model_id = _esc(result.get("model_id", ""))
    terminal_status = str(result.get("terminal_status") or "").lower()
    ts_color = _TERMINAL_COLORS.get(terminal_status, "#6b7280")
    ts_label = _esc(terminal_status or "unknown")
    final_summary = _esc(result.get("final_summary", ""))
    stuck_reason = _esc(result.get("stuck_reason", ""))
    error = _esc(result.get("error", ""))
    iterations = _fmt_int(result.get("iterations"))
    cost_usd = _fmt_usd(result.get("cost_usd"))
    max_usd = _fmt_usd(result.get("max_usd"))
    in_tok = _fmt_int(result.get("input_tokens"))
    out_tok = _fmt_int(result.get("output_tokens"))
    cache_r = _fmt_int(result.get("cache_read_tokens"))
    cache_w = _fmt_int(result.get("cache_write_tokens"))

    step_state = result.get("step_state") or []
    n_total = len(step_state)
    n_passed = sum(1 for s in step_state if s.get("status") == "passed")
    n_failed = sum(1 for s in step_state if s.get("status") == "failed")
    n_skipped = sum(1 for s in step_state if s.get("status") == "skipped")

    rows: list[str] = []
    for s in step_state:
        idx = _esc(s.get("index", ""))
        text = _esc(s.get("text", ""))
        status = str(s.get("status") or "pending")
        icon, color = _STATUS_BADGES.get(status, ("·", "#6b7280"))
        note = _esc(s.get("error") or s.get("note") or "")
        rows.append(
            f'<tr>'
            f'<td class="idx">{idx}</td>'
            f'<td class="text">{text}</td>'
            f'<td class="status" style="color:{color}">{icon} {_esc(status)}</td>'
            f'<td class="note">{note}</td>'
            f'</tr>'
        )
    steps_html = "\n".join(rows) if rows else (
        '<tr><td colspan="4" style="text-align:center;color:#6b7280;padding:1.5rem">'
        'No numbered AC steps were provided for this run.</td></tr>'
    )

    banner_html = ""
    if terminal_status and terminal_status != "done":
        reason_bits: list[str] = []
        if stuck_reason:
            reason_bits.append(f"<strong>Reason:</strong> {stuck_reason}")
        if error:
            reason_bits.append(f"<strong>Error:</strong> {error}")
        if final_summary:
            reason_bits.append(f"<strong>Summary:</strong> {final_summary}")
        detail_html = "<br>".join(reason_bits) if reason_bits else ""
        banner_html = (
            f'<div class="banner" style="background:{ts_color}22;border-left:4px solid {ts_color}">'
            f'<div><strong>Run ended with status:</strong> '
            f'<span style="color:{ts_color};text-transform:uppercase">{ts_label}</span></div>'
            f'{detail_html}'
            f'</div>'
        )
    elif final_summary:
        banner_html = (
            f'<div class="banner" style="background:{ts_color}22;border-left:4px solid {ts_color}">'
            f'<strong>Summary:</strong> {final_summary}'
            f'</div>'
        )

    video_html = _render_video(video_url)
    audit_html = _render_audit_trail(run_id_raw, screenshot_urls=screenshot_urls)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>vQA CU Run — {ticket_id or run_id}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 2rem; background: #f7f7f8; color: #111; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 0.5rem; }}
  h2 {{ font-size: 1.15rem; margin: 2rem 0 0.75rem; }}
  code {{ font-family: ui-monospace, Menlo, monospace; background: #f3f4f6; padding: 0.05rem 0.35rem; border-radius: 3px; font-size: 0.85em; }}
  .subhead {{ color: #6b7280; margin-bottom: 1.25rem; font-size: 0.9rem; }}
  .banner {{ padding: 1rem 1.25rem; border-radius: 6px; margin-bottom: 1.25rem; line-height: 1.55; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.75rem; margin-bottom: 1.5rem; }}
  .kpi {{ background: white; padding: 0.75rem 1rem; border-radius: 6px; border: 1px solid #e5e7eb; }}
  .kpi .label {{ font-size: 0.75rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; }}
  .kpi .value {{ font-size: 1.15rem; font-weight: 600; margin-top: 0.15rem; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 6px; overflow: hidden; border: 1px solid #e5e7eb; }}
  th {{ text-align: left; background: #f3f4f6; padding: 0.65rem 0.85rem; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px; color: #4b5563; border-bottom: 1px solid #e5e7eb; }}
  td {{ padding: 0.65rem 0.85rem; border-bottom: 1px solid #f3f4f6; vertical-align: top; font-size: 0.9rem; }}
  tr:last-child td {{ border-bottom: none; }}
  td.idx {{ font-family: ui-monospace, Menlo, monospace; color: #6b7280; width: 3rem; }}
  td.status {{ white-space: nowrap; font-weight: 500; width: 8rem; }}
  td.note {{ color: #4b5563; font-size: 0.85rem; }}
  .foot {{ margin-top: 1.25rem; font-size: 0.75rem; color: #6b7280; }}
  .muted {{ color: #6b7280; }}
  .section {{ margin-top: 1.5rem; }}
  .section-count {{ font-size: 0.85rem; color: #6b7280; font-weight: 400; }}
  .section-hint {{ font-size: 0.85rem; margin: 0 0 1rem; }}
  .err-badge {{ display: inline-block; padding: 0.05rem 0.5rem; border-radius: 10px; background: #fee2e2; color: #b91c1c; font-size: 0.75rem; margin-left: 0.35rem; font-weight: 500; }}
  .session-video {{ width: 100%; max-width: 900px; border-radius: 6px; background: #000; display: block; }}
  details.tech-stats {{ background: white; border: 1px solid #e5e7eb; border-radius: 6px; padding: 0.5rem 0.9rem; margin-bottom: 1rem; }}
  details.tech-stats > summary {{ cursor: pointer; font-size: 0.85rem; color: #4b5563; user-select: none; }}
  details.tech-stats[open] {{ padding-bottom: 0.85rem; }}
  .tech-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.6rem; margin-top: 0.75rem; }}
  .tech-grid .kpi {{ background: #f9fafb; }}
  details.iter {{ background: white; border: 1px solid #e5e7eb; border-radius: 6px; margin-bottom: 0.5rem; overflow: hidden; }}
  details.iter[open] {{ box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
  details.iter-error {{ border-left: 3px solid #c62828; }}
  details.iter-kickoff {{ border-left: 3px solid #6366f1; }}
  details.iter-bookkeeping {{ opacity: 0.85; }}
  details.iter-bookkeeping > summary {{ background: #fafafa; }}
  details.iter > summary {{ cursor: pointer; padding: 0.6rem 0.85rem; font-size: 0.9rem; user-select: none; list-style: none; display: flex; align-items: center; gap: 0.5rem; }}
  details.iter > summary::-webkit-details-marker {{ display: none; }}
  details.iter > summary::before {{ content: "▸"; display: inline-block; color: #9ca3af; transition: transform 0.15s; flex-shrink: 0; }}
  details.iter[open] > summary::before {{ transform: rotate(90deg); }}
  .iter-num {{ background: #f3f4f6; color: #4b5563; padding: 0.1rem 0.55rem; border-radius: 3px; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.3px; flex-shrink: 0; }}
  .iter-kickoff .iter-num {{ background: #eef2ff; color: #4338ca; }}
  .iter-summary {{ color: #1f2937; }}
  .iter-body {{ padding: 0.9rem 1rem 1rem; border-top: 1px solid #f3f4f6; }}
  .section-label {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px; color: #6b7280; margin: 1rem 0 0.4rem; font-weight: 600; }}
  .iter-body .section-label:first-child {{ margin-top: 0; }}
  .iter-screenshot {{ max-width: 100%; border: 1px solid #e5e7eb; border-radius: 4px; display: block; }}
  .reasoning, .prompt-text {{ white-space: pre-wrap; word-wrap: break-word; background: #f9fafb; padding: 0.7rem 0.85rem; border-radius: 4px; border: 1px solid #f3f4f6; font-size: 0.85rem; line-height: 1.55; color: #1f2937; margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  .tool-call {{ background: #f9fafb; border: 1px solid #f3f4f6; border-radius: 4px; padding: 0.65rem 0.75rem; margin-bottom: 0.5rem; }}
  .tool-human {{ font-size: 0.92rem; color: #1f2937; line-height: 1.5; }}
  .outcome {{ margin-top: 0.5rem; display: flex; align-items: flex-start; gap: 0.5rem; flex-wrap: wrap; }}
  .outcome-pill {{ display: inline-block; padding: 0.1rem 0.55rem; border-radius: 10px; font-size: 0.75rem; font-weight: 600; flex-shrink: 0; }}
  .outcome-pill.ok {{ background: #dcfce7; color: #166534; }}
  .outcome-pill.err {{ background: #fee2e2; color: #b91c1c; }}
  .outcome-text {{ white-space: pre-wrap; word-wrap: break-word; margin: 0; font-family: ui-monospace, Menlo, monospace; font-size: 0.78rem; color: #374151; background: transparent; flex: 1 1 100%; max-height: 220px; overflow: auto; }}
  .outcome-err .outcome-text {{ color: #991b1b; }}
  .marks-footer {{ margin-top: 0.75rem; padding: 0.4rem 0.65rem; background: #f9fafb; border-radius: 4px; font-size: 0.8rem; color: #4b5563; }}
  .marks-icon {{ margin-right: 0.35rem; }}
  .tool-raw {{ margin-top: 0.5rem; }}
  .tool-raw > summary {{ cursor: pointer; font-size: 0.72rem; color: #9ca3af; user-select: none; }}
  .tool-input {{ white-space: pre-wrap; word-wrap: break-word; margin: 0.3rem 0 0; font-family: ui-monospace, Menlo, monospace; font-size: 0.76rem; color: #374151; background: #ffffff; border: 1px solid #f3f4f6; border-radius: 3px; padding: 0.4rem 0.55rem; }}
</style>
</head>
<body>
  <h1>vQA Computer-Use Run — {ticket_id or run_id}</h1>
  <div class="subhead">
    run <code>{run_id}</code>
    · product <strong>{product}</strong>
    · model <code>{model_id}</code>
  </div>
  {banner_html}
  <div class="kpis">
    <div class="kpi"><div class="label">Outcome</div><div class="value" style="color:{ts_color}">{ts_label}</div></div>
    <div class="kpi"><div class="label">AC steps passed</div><div class="value">{n_passed} / {n_total}</div></div>
    <div class="kpi"><div class="label">Failed / Skipped</div><div class="value">{n_failed} / {n_skipped}</div></div>
    <div class="kpi"><div class="label">Actions taken</div><div class="value">{iterations}</div></div>
    <div class="kpi"><div class="label">Spend</div><div class="value">{cost_usd} <span style="color:#6b7280;font-weight:400;font-size:0.85rem">/ {max_usd}</span></div></div>
  </div>
  <details class="tech-stats">
    <summary>Technical details (tokens, cache, model)</summary>
    <div class="tech-grid">
      <div class="kpi"><div class="label">Tokens in / out</div><div class="value">{in_tok} / {out_tok}</div></div>
      <div class="kpi"><div class="label">Cache read / write</div><div class="value">{cache_r} / {cache_w}</div></div>
      <div class="kpi"><div class="label">Model</div><div class="value" style="font-size:0.85rem">{model_id or "—"}</div></div>
      <div class="kpi"><div class="label">Run ID</div><div class="value" style="font-size:0.85rem">{run_id or "—"}</div></div>
    </div>
  </details>
  <h2>Acceptance criteria</h2>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Test Step</th>
        <th>Result</th>
        <th>Note</th>
      </tr>
    </thead>
    <tbody>
      {steps_html}
    </tbody>
  </table>
  {video_html}
  {audit_html}
  <div class="foot">
    Generated by <code>backend.engine.computer_use.report</code> — CU-loop audit report.
  </div>
</body>
</html>
"""
