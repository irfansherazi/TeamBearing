"""
Playwright tool implementations for the Computer-Use loop.

Each tool takes a live Playwright Page and returns a compact string result
that becomes the next `tool_result` content block sent to the model.

Mostly minimal. Two exceptions on top of raw Playwright:
  1. `fill` auto-detects `span.tasp` / contenteditable and falls back to
     keyboard.type so one tool call handles the vPromotions rich-text
     spans without an N-turn click+press dance.
  2. `select2_pick` collapses the open-anchor → type-in-search → click-
     option select2 3.x dance into ONE tool call. Same widget shows up
     as Category, Stations, Client, Sales Assignment, Sales Person, and
     dozens of other fields in vPromotions.
  3. `lookup_selector` exposes the offline selector RAG index as a tool,
     so a stuck model can query for the correct selector mid-run instead
     of drifting into click_at pixel-guessing.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)


# Selectors matching span.tasp / contenteditable spans that must be filled
# with `fill()`, never plain-clicked. Plain click lands focus on the wrong
# element half the time (the tasp span itself is not focusable — its
# hidden sibling input is), which then leads the model into click_at spam.
# Matches:
#   `.tasp` / `span.tasp` — class-based selectors
#   `[id$='_tasp']` / `[id$="_..._tasp"]` — id-suffix attribute selectors
#   `#foo_description_tasp` — id ending in _tasp (word-boundary)
_TASP_SELECTOR_RE = re.compile(
    r"(?:^|[\s>])\.tasp(?![a-z0-9_-])"
    r"|span\.tasp(?![a-z0-9_-])"
    r"|_tasp['\"\]\s]"
    r"|_tasp$",
    re.IGNORECASE,
)

# CSS "anchor" characters — presence of any means the string is very likely
# an actual CSS selector, not a natural-language label. Order chosen for the
# common formbuilder patterns: `[id$=...]`, `.class`, `#id`, `>`, `~`, `+`,
# pseudo-selectors like `:visible`, `:has(...)`, universal `*`.
_CSS_ANCHOR_CHARS = frozenset("[].#>~+:*")


def _looks_like_natural_language(target: str) -> bool:
    """
    Heuristic: is this target a natural-language label misused as a CSS
    selector? Two signals fire:
      1. contains "..." (a truncation ellipsis — three literal dots — which
         is never a valid CSS token because `.` starts a class name and
         `..` is a parse error).
      2. contains whitespace AND has zero CSS anchor characters
         (`[`, `.`, `#`, `>`, `~`, `+`, `:`, `*`).
    Bare tag names like "input" or "div" have no whitespace and no anchors
    — those pass through untouched (a valid, if broad, CSS selector).
    """
    if not target:
        return False
    if "..." in target:
        return True
    if any(c.isspace() for c in target) and not any(c in _CSS_ANCHOR_CHARS for c in target):
        return True
    return False

# Anthropic tool schemas — sent to Claude on every turn.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "click",
        "description": "Click a visible element on the page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Visible text, label, role name, or CSS selector for the element to click.",
                },
                "hint": {
                    "type": "string",
                    "enum": ["text", "role", "label", "css"],
                    "description": "How to interpret `target`. Default 'text'.",
                    "default": "text",
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "click_at",
        "description": (
            "Click at absolute pixel coordinates on the CURRENT screenshot. "
            "Use ONLY as a fallback after semantic click has failed twice on the "
            "same visual target. Read x,y from the screenshot you were just shown "
            "— do NOT guess. Coordinates are pixels in the screenshot's own "
            "coordinate system (top-left = 0,0). vQA converts them to the "
            "browser's CSS pixel space internally."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X pixel in the screenshot."},
                "y": {"type": "integer", "description": "Y pixel in the screenshot."},
                "reason": {
                    "type": "string",
                    "description": "Which element you are targeting and why semantic click failed.",
                },
            },
            "required": ["x", "y", "reason"],
        },
    },
    {
        "name": "fill",
        "description": "Type a value into a text input, textarea, or contenteditable.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Label, placeholder, or CSS selector for the input.",
                },
                "value": {
                    "type": "string",
                    "description": "The text to type into the input.",
                },
                "hint": {
                    "type": "string",
                    "enum": ["label", "placeholder", "role", "css"],
                    "description": "How to interpret `target`. Default 'label'.",
                    "default": "label",
                },
            },
            "required": ["target", "value"],
        },
    },
    {
        "name": "type_text",
        "description": (
            "Type text into the currently focused element via the keyboard. "
            "Use as a fallback when `fill` fails due to locator timeout or "
            "'not an <input>' errors — click the target field first (via "
            "`click` or `click_at`) to focus it, then call `type_text`. "
            "Types the entire string in ONE tool call — do NOT fall back to "
            "individual `press(key)` calls for multi-character strings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to type into the currently focused element.",
                },
                "clear_first": {
                    "type": "boolean",
                    "description": (
                        "If true (default), select-all + delete the focused "
                        "element's content before typing. Makes repeated "
                        "calls idempotent."
                    ),
                    "default": True,
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "select",
        "description": "Set the selected option(s) on a native <select> element. For multi-select, pass multiple values.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Label, name attribute, or CSS selector for the <select> element.",
                },
                "values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Option label(s) to select. Single-element list for single-select.",
                },
            },
            "required": ["target", "values"],
        },
    },
    {
        "name": "select2_pick",
        "description": (
            "Pick an option in a Select2 3.x dropdown in ONE tool call. "
            "Use this for vPromotions dropdowns such as Category, Stations, "
            "Client, Sales Assignment, Sales Person, Jock Requested, Tickets "
            "For An Event — anything rendered as a select2 anchor with a "
            "search input that appears in a body-mounted overlay. Handles "
            "both static and AJAX-backed variants. Do NOT use `click_at` on "
            "these fields — this tool is faster and does not depend on pixel "
            "coordinates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "anchor": {
                    "type": "string",
                    "description": (
                        "CSS selector for the select2 anchor. Common shapes: "
                        "`#prf_form_rightview [id^='s2id_'][id$='_client'] a.select2-choice`, "
                        "`#prf_form_rightview [id^='s2id_'][id$='_stations'] ul.select2-choices`. "
                        "The tool auto-clicks whatever this locates to open the drop."
                    ),
                },
                "option": {
                    "type": "string",
                    "description": (
                        "The option's visible text (or a distinctive substring). "
                        "Matched case-insensitively against the drop's list "
                        "items. Also typed into the search input to filter, "
                        "which triggers AJAX-backed variants."
                    ),
                },
                "ajax_wait_ms": {
                    "type": "integer",
                    "description": (
                        "Optional wait (ms) after typing before picking the "
                        "option. Default 800ms — enough for AJAX-backed "
                        "typeaheads (Client, Sales Person). Static drops "
                        "settle in <200ms."
                    ),
                    "default": 800,
                },
            },
            "required": ["anchor", "option"],
        },
    },
    {
        "name": "lookup_selector",
        "description": (
            "Query the vQA selector registry for the correct CSS selector, "
            "recipe, or widget contract for a UI element. Use this the "
            "moment you are stuck on a widget — before escalating to "
            "`click_at` pixel guessing. Returns up to ~2KB of matched "
            "registry entries + relevant blueprint skills. Free-text query — "
            "describe the field ('Description tasp on PRF drawer', 'Sales "
            "Assignment select2', 'Home button in vPromotions navbar')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text description of the element you're trying to interact with.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "press",
        "description": "Press a keyboard key like 'Enter', 'Escape', 'Tab', 'ArrowDown'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Playwright key name.",
                },
            },
            "required": ["key"],
        },
    },
    {
        "name": "navigate",
        "description": "Navigate the browser to a URL. Use sparingly — most work happens by clicking within the current app.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "wait",
        "description": "Wait for the page to settle. Use 1-3 seconds. Longer waits are a smell — call this only if the page is clearly loading.",
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "minimum": 0.5, "maximum": 10},
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "mark_step_status",
        "description": (
            "Mark one of the numbered AC steps in the current run as "
            "in_progress, passed, failed, or skipped. Use this so the UI "
            "reflects real-time progress — mark a step in_progress when you "
            "begin working on it, and passed the moment you observe the "
            "expected result. Failed = the step's expected outcome could NOT "
            "be produced (e.g. required-field validation didn't fire). "
            "Skipped = the step is not applicable in this environment. "
            "Do NOT wait until `done` to mark everything — mark as you go."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "description": "0-based index of the step (as numbered in the initial user message).",
                },
                "status": {
                    "type": "string",
                    "enum": ["in_progress", "passed", "failed", "skipped"],
                },
                "note": {
                    "type": "string",
                    "description": "Short observation. Populated on failed steps as the error field.",
                },
            },
            "required": ["index", "status"],
        },
    },
    {
        "name": "run_scripted_flow",
        "description": (
            "Execute a hand-authored product macro that collapses a documented "
            "multi-step recipe into ONE tool call. Prefer this over driving the "
            "form field-by-field when the AC targets a supported flow — a single "
            "call replaces 50+ click/fill/wait iterations.\n\n"
            "Available flows:\n"
            "  createPrfHappyPath — Open the New-PRF drawer, fill "
            "title/category/stations/sales_assignment/start_datetime/end_datetime/"
            "description, and click Save (or Save as Draft when save_as='draft'). "
            "Returns record_id on success. Use for AC that says 'create a PRF' / "
            "'submit a new PRF' / 'save a PRF as draft'. Args: "
            "{title: str (required), category: str|list[str] (default 'Contest'), "
            "stations: list[str], sales_assignment: str, "
            "start_datetime: 'MM-DD-YYYY hh:mm A' (default +7d 09:00), "
            "end_datetime: 'MM-DD-YYYY hh:mm A' (default +8d 09:00), "
            "description: str, save_as: 'submit'|'draft' (default 'submit'), "
            "extra_text_fields: dict[str,str]}.\n\n"
            "When the AC has requirements beyond what the flow's args cover, "
            "call the flow first for the boilerplate then use individual tools "
            "for the delta. Do NOT call this flow twice back-to-back without "
            "checking the screenshot first — a duplicate call would open a "
            "second drawer over the first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Which flow to run (e.g. 'createPrfHappyPath').",
                },
                "args": {
                    "type": "object",
                    "description": "Flow-specific arguments (see flow docs above).",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "done",
        "description": "Declare the acceptance criteria fully verified. Ends the run.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Short summary of what was accomplished.",
                },
            },
            "required": ["summary"],
        },
    },
    {
        "name": "request_help",
        "description": "Declare that the loop is stuck and needs a human to take over. Use only after multiple attempts have failed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Specific reason for the escalation (what was attempted, what failed).",
                },
            },
            "required": ["reason"],
        },
    },
]


def _resolve_click_locator(page: Page, target: str, hint: str):
    """Build a Playwright locator from a target + hint."""
    hint = (hint or "text").lower().strip()
    if hint == "role":
        # Model may pass "button", "link", "checkbox", or a role:name form.
        # Heuristic: if target looks like a role name only, use it; otherwise
        # treat target as the accessible name and use "button" as default role.
        role_names = {"button", "link", "checkbox", "radio", "textbox", "combobox",
                      "option", "menuitem", "tab", "listitem", "row", "cell"}
        t = target.strip().lower()
        if t in role_names:
            return page.get_by_role(t)
        # Assume caller means "any interactive with this name" → try button first
        return page.get_by_role("button", name=target)
    if hint == "label":
        return page.get_by_label(target)
    if hint == "css":
        return page.locator(target)
    # default: text
    return page.get_by_text(target, exact=False)


def _resolve_fill_locator(page: Page, target: str, hint: str):
    hint = (hint or "label").lower().strip()
    if hint == "placeholder":
        return page.get_by_placeholder(target)
    if hint == "role":
        return page.get_by_role("textbox", name=target)
    if hint == "css":
        return page.locator(target)
    # default: label
    return page.get_by_label(target)


def _resolve_select_locator(page: Page, target: str):
    """<select> can be addressed by label, name attr, or CSS."""
    # Try label first
    if not (target.startswith("#") or target.startswith(".") or target.startswith("[") or "select" in target.lower()):
        return page.get_by_label(target)
    # Otherwise treat as CSS selector
    return page.locator(target)


async def tool_click(page: Page, args: dict[str, Any]) -> str:
    target = args.get("target", "")
    hint = args.get("hint", "text")
    if not target:
        return "error: click called without a target"
    # Reject clicks on span.tasp / contenteditable spans. Plain click on a
    # tasp lands focus on a non-focusable node — the model then loops on
    # click_at trying to force focus. `fill()` has proper contenteditable
    # handling; route the model there.
    if hint == "css" and _TASP_SELECTOR_RE.search(target):
        return (
            f"error: click on tasp element {target!r} rejected — this is a "
            f"contenteditable rich-text span, not a focusable input. Use "
            f"`fill(target={target!r}, hint=\"css\", value=<text>)` instead — "
            f"the runtime auto-detects contenteditable and types via keyboard. "
            f"Do NOT use `click_at` on tasp fields."
        )
    # Defensive guard: catch the "natural-language target with hint='css'"
    # confusion where the model uses a visible label as if it were a CSS
    # selector (e.g. `click(target="Select Person...", hint="css")`). CSS
    # ellipsis is a `.` — Playwright errors with "Unexpected token" and the
    # model loops on the same mistake. If the target contains "..." (a text
    # truncation marker, not valid CSS) or has whitespace with no CSS
    # anchors, return a specific error that names the fix.
    if hint == "css" and _looks_like_natural_language(target):
        return (
            f"error: click called with hint=\"css\" but target {target!r} looks "
            f"like natural-language text, not a CSS selector. If you meant to "
            f"click the visible label, retry with hint=\"text\". If you meant "
            f"to click a CSS-identified element, pass the selector itself "
            f"(e.g. \"[id$='_field']\", \".btn_copy_prf\", or the REUSABLE_CSS_"
            f"SELECTOR previously echoed by click_at) — NOT the visible label."
        )
    try:
        loc = _resolve_click_locator(page, target, hint)
        await loc.first.click(timeout=10_000)
        return f"clicked {hint}:{target!r}"
    except PlaywrightTimeoutError as e:
        return (
            f"error: click timeout on {hint}:{target!r} — element not visible/"
            f"clickable within 10s. Consider whether the target is inside a "
            f"closed dropdown that must be opened first. If you retried and "
            f"it's still failing, call `lookup_selector(query={target!r})` for "
            f"the correct selector before falling back to `click_at`."
        )
    except Exception as e:
        msg = str(e).split("\n")[0][:300]
        return (
            f"error: click failed on {hint}:{target!r} — {msg}. "
            f"If this is the second failure on the same target, call "
            f"`lookup_selector(query={target!r})` for the correct selector "
            f"before escalating to `click_at`."
        )


async def tool_click_at(page: Page, args: dict[str, Any]) -> str:
    """
    Coordinate-based click. Model gives (x, y) in screenshot pixel space;
    we convert to CSS pixels using the metadata stashed on `page` by the
    most recent screenshot capture, then dispatch page.mouse.click.

    After the click, we run `document.elementFromPoint(css_x, css_y)` and
    echo a compact description of what was actually hit — tag, id, primary
    class, first ancestor with an id. Without this feedback the model
    has no way to know a coordinate missed, and drifts into pixel-guessing
    loops.

    If metadata is missing (screenshot helper not run yet, or was skipped),
    we treat the incoming coords as already-CSS pixels — degrades but does
    not crash.
    """
    try:
        model_x = int(args.get("x"))
        model_y = int(args.get("y"))
    except (TypeError, ValueError):
        return "error: click_at requires integer x and y"
    reason = str(args.get("reason", "")).strip()[:200]

    meta = getattr(page, "_vqa_click_meta", None) or {}
    ss_w = meta.get("screenshot_w")
    ss_h = meta.get("screenshot_h")
    vp_w = meta.get("viewport_w")
    vp_h = meta.get("viewport_h")

    if ss_w and ss_h and vp_w and vp_h:
        css_x = model_x * vp_w / ss_w
        css_y = model_y * vp_h / ss_h
        scale_note = f"(model {model_x},{model_y} on {ss_w}x{ss_h} → css {css_x:.1f},{css_y:.1f} on {vp_w}x{vp_h})"
    else:
        # No metadata — assume model output is already CSS pixels.
        css_x, css_y = float(model_x), float(model_y)
        scale_note = "(no screenshot metadata; treating coords as CSS pixels)"

    try:
        await page.mouse.click(css_x, css_y)
    except Exception as e:
        msg = str(e).split("\n")[0][:300]
        return f"error: click_at failed at css ({css_x:.1f},{css_y:.1f}) — {msg}"

    # Echo what landed under the cursor. Non-fatal if the eval fails —
    # feedback is a bonus, not a requirement.
    hit_desc = await _describe_element_at(page, css_x, css_y)
    hit_note = f" — hit: {hit_desc}" if hit_desc else ""
    return f"click_at ok {scale_note}{hit_note} — reason={reason!r}"


async def _describe_element_at(page: Page, css_x: float, css_y: float) -> str:
    """
    Return a short human-readable description of the element under
    (css_x, css_y). Used by tool_click_at to echo feedback so the model
    can tell when a coordinate missed. Silent-fail on any error.

    Also computes a stable selector suggestion (data-cy, aria-label,
    id-suffix, or ancestor+tag+class) so the model can upgrade from
    coordinate-based clicks to selector-based clicks on repeat hits.
    Without this suggestion, click_at is a one-way ratchet — every
    coordinate is another blind pixel guess with no path to stability.
    """
    try:
        info = await page.evaluate(
            "(pt) => {"
            " const el = document.elementFromPoint(pt.x, pt.y);"
            " if (!el) return null;"
            " const attr = (node, name) => (node && node.getAttribute) ? (node.getAttribute(name) || '') : '';"
            " let anc = el;"
            " let ancId = '';"
            " while (anc && !ancId) {"
            "  if (anc.id) { ancId = anc.id; break; }"
            "  anc = anc.parentElement;"
            " }"
            " const cls = (el.className || '').toString().split(/\\s+/).filter(Boolean).slice(0, 2).join('.');"
            # Walk up to 5 ancestors looking for a stable anchor:
            # data-cy, id-suffix (formbuilder), full id, or aria-label.
            " let stable = '';"
            " let stableKind = '';"
            " let node = el;"
            " for (let i = 0; i < 5 && node && node.getAttribute; i++, node = node.parentElement) {"
            "  const dc = attr(node, 'data-cy');"
            "  if (dc) { stable = `[data-cy='${dc}']`; stableKind = 'data-cy'; break; }"
            "  const nid = node.id || '';"
            # formbuilder pattern: id ends with '_<field>' (optionally '_tasp')
            "  if (nid && /_[a-z0-9]+(_tasp)?$/i.test(nid)) {"
            "   const suf = nid.slice(nid.lastIndexOf('_', nid.endsWith('_tasp') ? nid.length - 6 : nid.length - 1));"
            "   stable = `[id$='${suf}']`; stableKind = 'id-suffix'; break;"
            "  }"
            "  if (nid) { stable = `#${nid}`; stableKind = 'id'; break; }"
            "  const al = attr(node, 'aria-label');"
            "  if (al) { stable = `[aria-label='${al.replace(/'/g, \"\\\\'\").slice(0, 60)}']`; stableKind = 'aria-label'; break; }"
            " }"
            " return {"
            "  tag: (el.tagName || '').toLowerCase(),"
            "  id: el.id || '',"
            "  cls: cls,"
            "  text: (el.innerText || el.textContent || '').trim().slice(0, 60),"
            "  ancestorId: ancId && ancId !== el.id ? ancId : '',"
            "  stableSelector: stable,"
            "  stableKind: stableKind"
            " };"
            "}",
            {"x": css_x, "y": css_y},
        )
    except Exception:
        return ""
    if not info:
        return "no element (outside viewport?)"
    parts = [f"<{info.get('tag') or '?'}"]
    if info.get("id"):
        parts.append(f" id={info['id']!r}")
    if info.get("cls"):
        parts.append(f" class={info['cls']!r}")
    parts.append(">")
    # Format the visible text as `visible:` (NOT `text=`) so the model
    # cannot confuse it with the `target=` slot in a subsequent click call.
    # Observed regression: prior format `text='Select Person...'` alongside
    # a `click(target=..., hint="css")` template caused the model to
    # substitute the label as the target with hint="css".
    if info.get("text"):
        parts.append(f" visible:{info['text']!r}")
    if info.get("ancestorId"):
        parts.append(f" (inside #{info['ancestorId']})")
    stable = (info.get("stableSelector") or "").strip()
    kind = (info.get("stableKind") or "").strip()
    if stable:
        # Emit the selector on its own labeled line — NO template invocation
        # with a `target=` placeholder — so the model reads "here is a
        # selector to reuse" and not a fill-in-the-blank click template.
        parts.append(f" | REUSABLE_CSS_SELECTOR={stable!r} (via {kind})")
    return "".join(parts)


async def tool_fill(page: Page, args: dict[str, Any]) -> str:
    """
    Type a value into a form control OR contenteditable.

    Contenteditable path: Playwright's `.fill()` throws "Element is not an
    <input>" on contenteditable spans (vPromotions uses `span.tasp` for
    Description / Play Copy / Prize Info / Liner Copy / Liner Notes). Rather
    than surfacing that error and forcing the model to redispatch as a click
    + N press() calls (~30-100 tool calls for a real-length string), we
    detect contenteditable up-front and dispatch a single `page.keyboard.type`
    against the focused element. The model's tool call succeeds on the first
    try — saving both wall-clock time and Bedrock spend on the retry path
    the old code always sent us down.
    """
    target = args.get("target", "")
    value = args.get("value", "")
    hint = args.get("hint", "label")
    if not target:
        return "error: fill called without a target"
    try:
        loc = _resolve_fill_locator(page, target, hint)
        first = loc.first

        # Pre-flight: is this a contenteditable / span.tasp / non-input?
        # We evaluate in-page so we don't need a second Playwright roundtrip
        # to discover the element type on the error path.
        editable_info: dict | None = None
        try:
            editable_info = await first.evaluate(
                "el => ({"
                " tag: (el.tagName || '').toLowerCase(),"
                " isContentEditable: !!el.isContentEditable,"
                " classes: (el.className || '').toString(),"
                " isTasp: (el.classList && el.classList.contains && el.classList.contains('tasp')) === true"
                "})",
                timeout=5_000,
            )
        except Exception:
            editable_info = None

        needs_type = bool(
            editable_info
            and (
                editable_info.get("isContentEditable")
                or editable_info.get("isTasp")
                or (editable_info.get("tag") in {"span", "div"} and "tasp" in (editable_info.get("classes") or ""))
            )
        )

        if needs_type:
            # Click to focus the caret, clear any prior content via
            # keyboard-select-all + delete, then type. The select-all is
            # what makes a repeat fill idempotent — otherwise the second
            # fill appends to the first fill's text.
            await first.click(timeout=5_000)
            try:
                await page.keyboard.press("Control+a")
                await page.keyboard.press("Delete")
            except Exception:
                pass  # non-fatal — proceed to type
            await page.keyboard.type(value)
            return (
                f"typed {value!r} into contenteditable {hint}:{target!r} "
                f"(fill auto-fell-back to keyboard.type: element is "
                f"{editable_info.get('tag')} tasp={editable_info.get('isTasp')} "
                f"contenteditable={editable_info.get('isContentEditable')})"
            )

        await first.fill(value, timeout=10_000)
        return f"filled {hint}:{target!r} with {value!r}"
    except PlaywrightTimeoutError:
        return (
            f"error: fill timeout on {hint}:{target!r}. "
            f"If this is the second failure on the same target, call "
            f"`lookup_selector(query={target!r})` for the correct selector "
            f"first. Alternatively, `click` on the field to focus it, then "
            f"`type_text(text=...)` to type the value in one call — do NOT "
            f"fall back to individual `press(key)` calls for multi-character strings."
        )
    except Exception as e:
        msg = str(e).split("\n")[0][:300]
        # Guide the model on the residual "Element is not an <input>" case
        # (happens if pre-flight evaluate failed to return editable info,
        # e.g. the locator matched a synthetic node). The hint below is
        # what the model should try next.
        if "not an <input>" in msg.lower() or "not an <input> or <textarea>" in msg.lower():
            return (
                f"error: fill failed on {hint}:{target!r} — {msg}. "
                f"This target appears to be contenteditable, not an <input>. "
                f"Retry with `hint=\"css\"` and a precise selector "
                f"(e.g. `span.tasp[id$='_<field>_tasp']`) — the runtime "
                f"auto-falls-back to keyboard-typing on contenteditable "
                f"once the locator is a single element. Alternatively, "
                f"`click_at` the field to focus it, then `type_text(text=...)`."
            )
        return (
            f"error: fill failed on {hint}:{target!r} — {msg}. "
            f"Try `click_at` on the field first to focus it, then "
            f"`type_text(text=...)` to type the value in one call — do NOT "
            f"fall back to individual `press(key)` calls for multi-character strings."
        )


async def tool_type_text(page: Page, args: dict[str, Any]) -> str:
    """
    Type a string into whatever element currently has focus.

    This is the bridge between `fill` (which needs a working locator) and
    `press` (which is one key per Bedrock round-trip). When `fill` fails —
    locator timeout, 'not an <input>' error on standard inputs, or any other
    resolution failure — the model should click the target field to focus
    it, then call this tool with the entire string in one shot.

    Deliberately minimal: no locator resolution, no element detection. If
    nothing has focus, `page.keyboard.type` types into the body element,
    which is usually a no-op — the model will see that on the next
    screenshot and know to click a field first.
    """
    text = args.get("text", "")
    if text == "":
        return "error: type_text called without text"
    clear_first = args.get("clear_first", True)
    try:
        if clear_first:
            # Same idempotency pattern as the contenteditable path in
            # tool_fill — Ctrl+A then Delete wipes the focused element's
            # content before we type the new value.
            try:
                await page.keyboard.press("Control+a")
                await page.keyboard.press("Delete")
            except Exception:
                pass  # non-fatal — proceed to type
        await page.keyboard.type(text)
        return f"typed {len(text)} chars into focused element"
    except Exception as e:
        msg = str(e).split("\n")[0][:300]
        return f"error: type_text failed — {msg}"


async def tool_select(page: Page, args: dict[str, Any]) -> str:
    target = args.get("target", "")
    values = args.get("values", []) or []
    if not target or not values:
        return "error: select called without target or values"
    try:
        loc = _resolve_select_locator(page, target)
        # Try select_option with label first (works for native <select>)
        try:
            await loc.first.select_option(label=values if len(values) > 1 else values[0], timeout=10_000)
            return f"selected {values!r} in {target!r}"
        except Exception:
            # Fallback: try selecting by value attribute
            await loc.first.select_option(value=values if len(values) > 1 else values[0], timeout=10_000)
            return f"selected {values!r} in {target!r} (by value)"
    except PlaywrightTimeoutError:
        return f"error: select timeout on {target!r} — element may not be a native <select>. If it's a custom dropdown (select2, PrimeNG, etc.), click to open then click each option."
    except Exception as e:
        msg = str(e).split("\n")[0][:300]
        return f"error: select failed on {target!r} — {msg}. If not a native <select>, use click to open the dropdown then click options individually."


async def tool_press(page: Page, args: dict[str, Any]) -> str:
    key = args.get("key", "")
    if not key:
        return "error: press called without a key"
    try:
        await page.keyboard.press(key)
        return f"pressed {key!r}"
    except Exception as e:
        return f"error: press failed — {e}"


async def tool_navigate(page: Page, args: dict[str, Any]) -> str:
    url = args.get("url", "")
    if not url:
        return "error: navigate called without a url"
    try:
        # domcontentloaded — not networkidle. Legacy apps poll and networkidle
        # never fires. domcontentloaded is enough; the SpaHydration barrier
        # below covers the actual post-load render.
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except PlaywrightTimeoutError:
        return f"error: navigate timeout on {url!r}"
    except Exception as e:
        msg = str(e).split("\n")[0][:300]
        return f"error: navigate failed on {url!r} — {msg}"
    # Post-nav hydration barrier. Without this, the next screenshot the
    # runner takes captures a mid-transition DOM and the model burns an
    # iteration re-navigating to the same URL. Bounded 2s cap — same
    # budget the LangGraph executor uses after page.goto.
    settle = await _settle_after_action(page, cap_ms=2000)
    return f"navigated to {url!r}{settle}"


async def _settle_after_action(page: Page, cap_ms: int = 1500) -> str:
    """
    Wait for the SPA to reach a stable state after a route- or state-
    changing action. Non-fatal on any error — returns an empty string
    on failure so the caller's success line stays intact.

    Uses SpaHydration when available (Angular-aware event-driven barrier
    with fixed fallback). Import is deferred so the CU module remains
    importable in test environments that don't have the browser package
    on sys.path.
    """
    try:
        from backend.browser.spa_hydration import SpaHydration
    except Exception:
        return ""
    try:
        result = await SpaHydration(enabled=True, timeout_ms=cap_ms).wait_for_stable(page)
        return f" (spa_settle={result.strategy_used} {result.elapsed_ms}ms)"
    except Exception:
        return ""


async def tool_wait(page: Page, args: dict[str, Any]) -> str:
    seconds = float(args.get("seconds", 1.0))
    seconds = max(0.5, min(10.0, seconds))
    await asyncio.sleep(seconds)
    return f"waited {seconds:.1f}s"


async def tool_mark_step_status(page: Page, args: dict[str, Any]) -> str:
    """
    Stage an AC-step status update. The runner drains
    `page._vqa_ac_update` after dispatch and broadcasts an ac_progress
    WebSocket event; the tool itself is a passthrough because it does not
    know the run_id.

    Silent no-op if `index` is missing or non-integer — never crashes the loop.
    """
    try:
        idx = int(args.get("index"))
    except (TypeError, ValueError):
        return "error: mark_step_status requires integer index"
    status = str(args.get("status", "")).strip()
    allowed = {"in_progress", "passed", "failed", "skipped"}
    if status not in allowed:
        return f"error: mark_step_status status must be one of {sorted(allowed)}"
    note = str(args.get("note", "")).strip()[:500]

    try:
        page._vqa_ac_update = {"index": idx, "status": status, "note": note}
    except Exception:
        pass
    return f"marked step {idx} as {status}"


async def tool_select2_pick(page: Page, args: dict[str, Any]) -> str:
    """
    Open a Select2 3.x anchor, type the option text into its search input,
    and click the matching drop option — all in one tool call.

    Handles both static drops (Category, Stations) and AJAX-backed
    typeaheads (Client, Sales Person). Search input is body-mounted in
    `div.select2-drop.select2-drop-active` for select2 3.x.

    Returns a compact string so the model reads a single line back per
    tool call: `select2_pick ok — picked 'Contest' from '#..._category'`.
    """
    anchor = str(args.get("anchor", "")).strip()
    option = str(args.get("option", "")).strip()
    if not anchor or not option:
        return "error: select2_pick requires both 'anchor' and 'option'"
    try:
        ajax_wait_ms = int(args.get("ajax_wait_ms", 800))
    except (TypeError, ValueError):
        ajax_wait_ms = 800
    ajax_wait_ms = max(0, min(5000, ajax_wait_ms))

    try:
        anchor_loc = page.locator(anchor).first
        await anchor_loc.click(timeout=10_000)
    except PlaywrightTimeoutError:
        return (
            f"error: select2_pick could not click anchor {anchor!r} within 10s. "
            f"Verify the anchor CSS with `lookup_selector` — a common shape is "
            f"`#prf_form_rightview [id^='s2id_'][id$='_<field>'] a.select2-choice`."
        )
    except Exception as e:
        msg = str(e).split("\n")[0][:300]
        return f"error: select2_pick failed to click anchor {anchor!r} — {msg}"

    # Wait for the active drop to mount. Select2 3.x reuses ONE
    # body-level container across all widgets — `div.select2-drop-active`.
    try:
        await page.locator("div.select2-drop.select2-drop-active").first.wait_for(
            state="visible", timeout=5_000
        )
    except PlaywrightTimeoutError:
        return (
            f"error: select2_pick opened anchor {anchor!r} but no active "
            f"drop appeared (looked for `div.select2-drop.select2-drop-active`). "
            f"This may not be a select2 3.x widget — try `click` + `select` "
            f"if it's a native <select>, or use `lookup_selector` to find "
            f"the correct recipe."
        )

    # Type into whichever search input is now visible. The `.select2-input`
    # is what the widget's own event handlers listen to — writing directly
    # to the offscreen native <input> would bypass the search chain.
    search_input = page.locator(
        "div.select2-drop.select2-drop-active input.select2-input"
    ).first
    try:
        await search_input.wait_for(state="visible", timeout=3_000)
        await search_input.fill("")  # clear residual text from any prior drop
        await search_input.type(option, delay=15)  # per-char events → AJAX fires
    except PlaywrightTimeoutError:
        # Some select2 variants (tags multi-select) place the search input
        # inline in the choices row rather than in the drop. Fall through
        # to option-click without pre-filtering.
        logger.debug("select2_pick: search input not visible in drop — proceeding without filter")
    except Exception as e:
        msg = str(e).split("\n")[0][:300]
        logger.warning("select2_pick: typing into search input failed — %s", msg)

    # Give AJAX-backed variants time to fetch results before clicking.
    if ajax_wait_ms > 0:
        await asyncio.sleep(ajax_wait_ms / 1000.0)

    # Click the matching option. `.select2-result-selectable` filters out
    # disabled entries and category headers. Case-insensitive substring
    # match on the option's visible text.
    try:
        opt_loc = page.locator(
            f"div.select2-drop.select2-drop-active "
            f"li.select2-result-selectable:has-text({_js_str(option)})"
        ).first
        await opt_loc.click(timeout=5_000)
    except PlaywrightTimeoutError:
        # Fallback: pick first selectable result — common for AJAX
        # typeaheads where the visible text is a formatted variant of
        # what the model typed (e.g. "Sales Assistant [Your Radio Stations]").
        try:
            fallback = page.locator(
                "div.select2-drop.select2-drop-active li.select2-result-selectable"
            ).first
            await fallback.click(timeout=3_000)
            settle = await _settle_after_action(page, cap_ms=600)
            return (
                f"select2_pick ok — picked FIRST result (no substring match "
                f"for {option!r}) from anchor {anchor!r}{settle}. Verify on "
                f"the next screenshot; if wrong, retry with a more distinctive "
                f"option text."
            )
        except Exception:
            return (
                f"error: select2_pick opened {anchor!r} but found no "
                f"selectable option matching {option!r}. Escape and check "
                f"available options via screenshot, or use `lookup_selector` "
                f"for allowed values."
            )
    except Exception as e:
        msg = str(e).split("\n")[0][:300]
        return f"error: select2_pick failed picking option {option!r} — {msg}"

    settle = await _settle_after_action(page, cap_ms=600)
    return f"select2_pick ok — picked {option!r} from {anchor!r}{settle}"


def _js_str(s: str) -> str:
    """Quote a string for use inside a Playwright `:has-text(...)` filter.

    Playwright's has-text accepts double-quoted strings. Escape internal
    double quotes; don't try to escape backslashes since they're rare in
    UI labels and Playwright treats them literally inside the filter.
    """
    return '"' + s.replace('"', '\\"') + '"'


async def tool_lookup_selector(page: Page, args: dict[str, Any]) -> str:
    """
    Query the offline selector RAG index. Returns budget-capped selector
    entries + blueprint skills relevant to the query — same block the
    LangGraph planner injects at plan time, on-demand mid-run for a
    stuck CU loop.

    Import is deferred so the CU module remains importable without
    scikit-learn / rank_bm25 installed (test contexts).
    """
    query = str(args.get("query", "")).strip()
    if not query:
        return "error: lookup_selector called without a query"
    try:
        from backend.kb.selector_rag import selector_rag
    except Exception as e:
        return f"error: lookup_selector unavailable — selector_rag failed to import: {e}"
    try:
        block = selector_rag.query(query, max_chars=1800)
    except Exception as e:
        msg = str(e).split("\n")[0][:300]
        return f"error: lookup_selector query failed — {msg}"
    if not block:
        return (
            f"lookup_selector: no registry entries matched {query!r}. "
            f"Try a more descriptive query (include the widget type — 'select2', "
            f"'tasp', 'button', 'dropdown' — and the field name)."
        )
    return f"lookup_selector results for {query!r}:\n{block}"


# Terminal tools (returned from dispatcher as sentinel results)
_DONE_SENTINEL = "__cu_done__"
_HELP_SENTINEL = "__cu_help__"


async def tool_done(page: Page, args: dict[str, Any]) -> str:
    summary = args.get("summary", "")
    return f"{_DONE_SENTINEL}:{summary}"


async def tool_request_help(page: Page, args: dict[str, Any]) -> str:
    reason = args.get("reason", "")
    return f"{_HELP_SENTINEL}:{reason}"


async def tool_run_scripted_flow(page: Page, args: dict[str, Any]) -> str:
    """
    Invoke a hand-authored product macro registered in
    `backend.engine.computer_use.scripted_flows`. Import is deferred so the
    module remains importable when Playwright helper deps are stubbed out.
    """
    name = str(args.get("name") or "").strip()
    if not name:
        return "error: run_scripted_flow requires 'name'"
    flow_args = args.get("args") or {}
    if not isinstance(flow_args, dict):
        return "error: run_scripted_flow 'args' must be an object"
    try:
        from backend.engine.computer_use.scripted_flows import run_scripted_flow
    except Exception as e:
        return f"error: run_scripted_flow unavailable — {str(e)[:200]}"
    return await run_scripted_flow(page, name, flow_args)


TOOL_HANDLERS = {
    "click": tool_click,
    "click_at": tool_click_at,
    "fill": tool_fill,
    "type_text": tool_type_text,
    "select": tool_select,
    "select2_pick": tool_select2_pick,
    "lookup_selector": tool_lookup_selector,
    "press": tool_press,
    "navigate": tool_navigate,
    "wait": tool_wait,
    "mark_step_status": tool_mark_step_status,
    "run_scripted_flow": tool_run_scripted_flow,
    "done": tool_done,
    "request_help": tool_request_help,
}


async def dispatch_tool(page: Page, name: str, args: dict[str, Any]) -> tuple[str, str]:
    """
    Execute a tool by name and return (status, result_text).

    status is one of: "ok", "done", "help".
    result_text is the string content that goes into the next tool_result block.
    """
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return "ok", f"error: unknown tool {name!r}"
    result = await handler(page, args)
    if isinstance(result, str) and result.startswith(_DONE_SENTINEL):
        return "done", result.split(":", 1)[1] if ":" in result else ""
    if isinstance(result, str) and result.startswith(_HELP_SENTINEL):
        return "help", result.split(":", 1)[1] if ":" in result else ""
    return "ok", result
