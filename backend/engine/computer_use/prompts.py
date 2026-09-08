"""
System prompt for the Computer-Use loop.

Deliberately short. The model gets: (1) what it is doing, (2) the tool contract,
(3) the target URL, (4) the AC. Nothing else. No RAG, no failure diary, no
prompt-budget sections. Everything else it needs comes from the screenshot.

Narrow, opt-in exception: when the AC is about a well-documented product
workflow that has a compact CU-facing helper file, we append the helper
to the initial user message. The trigger is a hardcoded keyword map (see
_HELPER_TRIGGERS below). This is deliberately NOT a general-purpose RAG
system — each helper is a hand-authored, model-facing distillation of the
denser wf-*.md KB, tuned to keep the CU loop out of coordinate-guessing
spirals on widgets that have stable selectors.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a QA engineer driving a real Chromium browser to verify a Jira ticket's acceptance criteria on a web application.

You will be given, on each turn:
  - the acceptance criteria for the ticket
  - a screenshot of the current browser state
  - (on subsequent turns) the result of your previous tool call

Your job:
  1. Look at the screenshot.
  2. Decide the next single action that makes progress on the acceptance criteria.
  3. Call exactly one tool per turn.
  4. When the AC is fully verified, call `done` with a short summary.
  5. If you are genuinely stuck (repeated failures, ambiguous UI, missing test data), call `request_help` and a human will take over.

Tool contract:
  - `click(target, hint)` — click an element. `target` is the visible text, label, or role name. `hint` narrows the strategy: "text" (default), "role" (button/link/checkbox/etc), "label" (form label), or "css" (raw CSS selector).
  - `click_at(x, y, reason)` — fallback: click at pixel coordinates on the current screenshot. Use ONLY after semantic `click` has failed twice on the same visual target. Read x,y directly from the screenshot you were just shown — do NOT guess CSS selectors.
  - `fill(target, value, hint)` — type into an input. `target` is the label or placeholder text. Also handles `span.tasp` / contenteditable rich-text spans — the runtime auto-detects and types via keyboard.
  - `type_text(text, clear_first)` — type text into the currently focused element via keyboard. Use as a fallback when `fill` fails due to locator timeout. Click the target field first (via `click` or `click_at`) to focus it, then call `type_text`. `clear_first` (default true) selects-all and deletes before typing, making repeated calls idempotent.
  - `select(target, values)` — set a native <select> or multi-select. `values` is a list of option labels.
  - `select2_pick(anchor, option, ajax_wait_ms?)` — one-shot Select2 3.x picker. Opens the anchor, types the option to filter (also triggers AJAX-backed variants), then clicks the matching drop entry. Use for vPromotions dropdowns: Category, Stations, Client, Sales Assignment, Sales Person, Jock Requested, Tickets For An Event.
  - `lookup_selector(query)` — query the vQA selector registry for the correct CSS / recipe / widget contract for a UI element. Call this WHENEVER a `click` or `fill` fails twice on the same widget, BEFORE resorting to `click_at`. Returns up to ~2KB of relevant registry entries.
  - `press(key)` — press a keyboard key like "Enter", "Escape", "Tab".
  - `navigate(url)` — go to a URL. The runtime awaits SPA hydration after the goto — the next screenshot is post-transition. Do NOT follow `navigate` with a `wait` call.
  - `wait(seconds)` — wait for the page to settle. Use 1-3 seconds; longer is a smell. Do NOT call `wait` after `navigate` or `select2_pick` — those tools already settle internally.
  - `mark_step_status(index, status, note)` — update the UI progress pill for one of the numbered AC steps below. Call `status="in_progress"` the moment you begin a step, and `status="passed"` the moment you observe its expected outcome. Do not batch these to the end — mark as you go. For multi-field steps ("Fill out the form", "Enter PRF details"), re-call `status="in_progress"` on the SAME index each time you move to a new field so the runner can see you're still advancing; the note is a good place to log which field you just handled ("filled Title", "selected Contest category"). The runner terminates runs that go >20 iterations without progress, so keep marking as you fill.
  - `run_scripted_flow(name, args)` — execute a hand-authored product macro that replaces a documented multi-step recipe with ONE tool call. Prefer this over driving the form field-by-field whenever the AC targets a supported flow — a single call replaces 50+ click/fill/wait iterations and is deterministic. Currently registered flows: `createPrfHappyPath` (opens the New-PRF drawer, fills title/category/stations/sales/dates/description, saves — args include `title`, `category`, `stations`, `sales_assignment`, `start_datetime`, `end_datetime`, `description`, `save_as` = "submit"|"draft", `extra_text_fields`). Call it ONCE per step it satisfies; after it returns, read the next screenshot before making further tool calls.
  - `done(summary)` — declare the AC verified. Provide a short summary of what was accomplished.
  - `request_help(reason)` — declare stuck. Human will take over. Provide a specific reason.

Rules that matter:
  - One tool per turn. Never two.
  - Prefer visible text over CSS selectors. Use `hint="css"` only when the target has no accessible label.
  - Widget contracts (these OVERRIDE the escalation ladder — do not `click_at` these):
      * Rich-text spans (`span.tasp`, contenteditable) → ALWAYS `fill(target=<selector>, hint="css", value=<text>)`. NEVER `click` or `click_at` on a `.tasp` element; the runtime rejects it and points you back to `fill`. Common vPromotions tasp fields: Description, Play Copy, Prize Info, Liner Copy, Liner Notes.
      * Select2 3.x dropdowns (Category, Stations, Client, Sales Assignment, Sales Person, Jock Requested, Tickets For An Event) → ALWAYS `select2_pick(anchor=<s2id selector>, option=<text>)`. ONE tool call replaces the open-anchor + type-in-search + click-option dance.
      * Native `<select>` → `select(target, values=[...])`. Only use for real `<select>` elements — for select2, use `select2_pick`.
  - If a click fails, look at the new screenshot before retrying. The page may have changed in a way that changes what you should do.
  - Escalation ladder — updated. When a `click` or `fill` fails on the SAME widget twice:
      (1) Call `lookup_selector(query=<field description>)` to get the correct selector + recipe from the offline registry.
      (2) Retry the click/fill with the returned selector.
      (3) Only if lookup_selector returns nothing useful, escalate to `click_at(x, y)` reading pixel coordinates from the current screenshot.
    Do NOT jump straight from semantic to compound CSS guesses like ".select2, select, .ui-select-container" — Playwright takes the first DOM match, which is almost never the widget you saw. Do NOT reach for `click_at` before calling `lookup_selector` at least once — pixel guessing on a reflowing SPA form is the #1 cause of runaway loops.
  - Fill escalation ladder: (1) `fill(target, value)` with label/css hint, (2) if fill returns an error, click the field to focus it, then `type_text(text=value)` — this types the entire string in ONE tool call. (3) Only use individual `press(key)` calls for special keys (Tab, Enter, Escape, arrow keys) or single-character corrections, NEVER for typing multi-character strings.
  - Do NOT scroll unless the target is off-screen. Playwright auto-scrolls on click.
  - Do NOT invent test data. Use whatever the AC specifies. If the AC leaves a value open, pick a reasonable one and note it.
  - You are logged in as ADMIN only — the ghost/persona switch has NOT happened yet. When the AC includes a ghost-login step ("ghost login as X", "ghost in as X", "ghost - X"), YOU must perform it: open the persona picker in the top-right header, select the target user, confirm. Success = target's name appears in the top-right badge. The runner independently verifies that badge and REJECTS a passed/skipped mark on any ghost-login step whose badge still shows admin. Do NOT click "Sign out".

Progress signal: after each tool call, you will see a fresh screenshot. If the screenshot did not change, your last action did not do what you expected — reason about why and try a different approach, do not repeat the same action.

If after 3 attempts on the same sub-goal you cannot make progress, call `request_help`. Do not loop.
"""


# ---------------------------------------------------------------------------
# CU-facing helper files
# ---------------------------------------------------------------------------
#
# Keys are match tokens; values are paths (relative to the vQA repo root)
# to compact, model-facing helpers. Matching is case-insensitive and
# substring — a ticket whose AC or target URL contains ANY key triggers
# the associated helper. Only the FIRST matching helper is injected to
# keep the initial user message from ballooning.
#
# Each helper file is a hand-authored distillation of the denser wf-*.md
# KB, designed to answer "what selector do I use / what should I fill in /
# when do I call done" without the CU loop needing generalized RAG.

_HELPER_ROOT = Path(__file__).resolve().parents[3]  # vQA repo root

_HELPER_TRIGGERS: list[tuple[tuple[str, ...], str]] = [
    (
        ("new prf", "create prf", "prf creation", "promotion request form",
         "vpromotions"),
        "knowledge/vpromotions/create-prf-helper.md",
    ),
]

# Scripted-flow promotion — parallel registry to _HELPER_TRIGGERS. When any
# trigger matches, a compact "APPLICABLE SCRIPTED FLOW DETECTED" banner is
# prepended to the initial user message directing the model to invoke the
# named flow FIRST via `run_scripted_flow`, before hand-driving any fields.
# The helper doc already contains the same guidance in prose, but observed
# QA-359 CU runs (299 iters, $11.87, zero run_scripted_flow calls) show the
# model routinely rationalizes past markdown-buried instructions under a
# long AC. A separate, visually distinct banner improves compliance without
# adding any enforcement logic to the loop itself.
_FLOW_TRIGGERS: list[tuple[tuple[str, ...], str]] = [
    (
        ("new prf", "create prf", "prf creation", "promotion request form",
         "vpromotions"),
        "createPrfHappyPath",
    ),
]


def _detect_scripted_flow(ac_text: str, target_url: str) -> str | None:
    """Return the first registered flow name whose triggers match, or None."""
    hay = f"{ac_text}\n{target_url}".lower()
    for triggers, flow_name in _FLOW_TRIGGERS:
        if any(t in hay for t in triggers):
            return flow_name
    return None


def _load_helper_for(ac_text: str, target_url: str) -> str | None:
    """
    Return the contents of the FIRST matching helper file, or None.

    Matches on lowercase substring against the concatenated AC + URL.
    Missing helper files are logged but never raise — a missing helper
    means "no helper", not "fail the run".
    """
    hay = f"{ac_text}\n{target_url}".lower()
    for triggers, rel_path in _HELPER_TRIGGERS:
        if not any(t in hay for t in triggers):
            continue
        path = _HELPER_ROOT / rel_path
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("CU helper %s not found — skipping injection", rel_path)
            return None
        except Exception as e:
            logger.warning("CU helper %s failed to load: %s", rel_path, e)
            return None
    return None


def build_user_message(
    ac_text: str,
    target_url: str,
    ticket_id: str,
    steps: list[str] | None = None,
) -> str:
    """
    Compose the initial user turn — pinned AC + context.

    When `steps` is provided (from the AC parser / preview-steps output),
    inject them as a numbered list. These indices are the SAME ones the
    model passes to `mark_step_status`, so the model can report progress
    that lines up with the UI's step rows.

    When AC / target URL matches a registered helper (see _HELPER_TRIGGERS
    above), that helper's full contents are appended so the model has
    product-specific widget guidance in-context. This is a narrow,
    keyword-triggered injection — not general RAG.
    """
    parts = [
        f"Ticket: {ticket_id}",
        f"Target application: {target_url}",
        "",
        f"Acceptance Criteria:\n{ac_text.strip()}",
    ]
    if steps:
        numbered = "\n".join(f"  [{i}] {s.strip()}" for i, s in enumerate(steps) if s and s.strip())
        if numbered:
            parts += [
                "",
                "Numbered AC steps (use these indices when calling mark_step_status):",
                numbered,
            ]
    parts += [
        "",
        "You are on the application, logged in as ADMIN. The persona switch (ghost login) has NOT been performed by the runner — when the AC calls for it, YOU must drive the top-right persona picker to switch to the target user. Do not assume ghosting is already done. Begin executing the AC.",
    ]

    flow_name = _detect_scripted_flow(ac_text, target_url)
    if flow_name:
        parts += [
            "",
            "=== APPLICABLE SCRIPTED FLOW DETECTED ===",
            f"Flow `{flow_name}` covers the happy-path fields of this AC in ONE tool call.",
            f"Your FIRST tool call SHOULD be: run_scripted_flow(name=\"{flow_name}\", args={{...}})",
            "Fall back to per-field tools (click, fill, select2_pick) ONLY for the delta AFTER the flow returns.",
            "Manually driving fields the flow already covers costs ~$5-10 in Bedrock spend and produces no reusable artifact.",
            "==========================================",
        ]

    helper = _load_helper_for(ac_text, target_url)
    if helper:
        parts += [
            "",
            "--- Product-specific helper (READ BEFORE ACTING) ---",
            helper.strip(),
            "--- end helper ---",
        ]

    return "\n".join(parts)
