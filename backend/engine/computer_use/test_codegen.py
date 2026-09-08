"""
Playwright test codegen from a completed Computer-Use run.

Reads the per-iteration transcript files this run wrote to
``.logs/computer_use/{run_id}/`` and emits a ``.spec.ts`` file that
mirrors the run's browser interactions as Playwright code.

Design choices:

- Only runs on ``terminal_status == "done"`` runs — the caller
  (routes.py:save_run_as_test) is responsible for that gate.
- Emits ``.spec.ts`` (draft/WIP) not ``.test.ts`` — CU output is
  unvetted; a human review promotes it to ``.test.ts``. Per the
  playwright/ CLAUDE.md, ``.spec.ts`` files are ignored by the
  default runner, which is the correct default for auto-generated
  tests.
- Groups actions by ``mark_step_status(in_progress)`` transitions
  into ``test.step()`` blocks. The step's ``note`` becomes the
  block label — falls back to the numbered AC text (parsed from
  the initial user message) when no note is present.
- Non-progress tools (``mark_step_status``, ``done``, ``request_help``)
  are structural markers, not emitted as Playwright code.
- ``click_at(x, y)`` is the only tool that requires an LLM pass —
  the caller passes coords + the iter's screenshot to Bedrock and
  gets back a Playwright locator expression. Cached per (x, y)
  bucket within a run so repeated pixel clicks on the same widget
  reuse one inference call.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from backend.engine.computer_use.runner import (
    _get_bedrock_client,
    _model_id,
    _transcript_dir,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filename sanitization
# ---------------------------------------------------------------------------
#
# Mirrors codegen_session._slugify — lowercase, non-alphanumeric → single
# hyphen, strip leading/trailing hyphens, cap at 50 chars. Duplicated (not
# imported) so this module can stand alone and so we can tweak the cap
# without cross-impacting the manual-recording flow.
_SLUG_MAX_LEN = 50


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:_SLUG_MAX_LEN] or "unnamed"


# ---------------------------------------------------------------------------
# Tool → Playwright translations
# ---------------------------------------------------------------------------
#
# Direct 1:1 mappings for the deterministic tools. click_at is handled
# separately (see _infer_click_at_selector). mark_step_status / done /
# request_help are structural — they don't emit Playwright lines.


def _ts_string(s: Any) -> str:
    """Quote a string for embedding in TS single-quoted literals."""
    return "'" + str(s or "").replace("\\", "\\\\").replace("'", "\\'") + "'"


def _translate_click(args: dict) -> str:
    target = args.get("target", "")
    hint = (args.get("hint") or "text").lower()
    if hint == "css":
        return f"await page.locator({_ts_string(target)}).click();"
    if hint == "role":
        # target is a role like "button" — no name provided by tool,
        # emit a locator that a human will refine.
        return f"await page.getByRole({_ts_string(target)}).click();"
    if hint == "label":
        return f"await page.getByLabel({_ts_string(target)}).click();"
    # Default: text
    return f"await page.getByText({_ts_string(target)}).click();"


def _translate_fill(args: dict) -> str:
    target = args.get("target", "")
    value = args.get("value", "")
    hint = (args.get("hint") or "text").lower()
    if hint == "css":
        return f"await page.locator({_ts_string(target)}).fill({_ts_string(value)});"
    if hint == "label":
        return f"await page.getByLabel({_ts_string(target)}).fill({_ts_string(value)});"
    return f"await page.getByText({_ts_string(target)}).fill({_ts_string(value)});"


def _translate_type_text(args: dict) -> str:
    text = args.get("text", "")
    return f"await page.keyboard.type({_ts_string(text)});"


def _translate_select(args: dict) -> str:
    target = args.get("target", "")
    values = args.get("values") or []
    values_ts = "[" + ", ".join(_ts_string(v) for v in values) + "]"
    return f"await page.getByLabel({_ts_string(target)}).selectOption({values_ts});"


def _translate_press(args: dict) -> str:
    key = args.get("key", "")
    return f"await page.keyboard.press({_ts_string(key)});"


def _translate_navigate(args: dict) -> str:
    url = args.get("url", "")
    return f"await page.goto({_ts_string(url)});"


def _translate_wait(args: dict) -> str:
    seconds = args.get("seconds", 1)
    try:
        ms = int(float(seconds) * 1000)
    except (TypeError, ValueError):
        ms = 1000
    return f"await page.waitForTimeout({ms});"


_DIRECT_TRANSLATORS = {
    "click": _translate_click,
    "fill": _translate_fill,
    "type_text": _translate_type_text,
    "select": _translate_select,
    "press": _translate_press,
    "navigate": _translate_navigate,
    "wait": _translate_wait,
}


# ---------------------------------------------------------------------------
# click_at → selector inference (LLM-backed, per-run cached)
# ---------------------------------------------------------------------------
#
# Same 20px bucketing the runner's novel-action tracker uses — so a click
# and its subsequent verification-click on the same widget reuse the same
# inferred selector instead of paying Bedrock twice.
_CLICK_AT_BUCKET_PX = 20


_CLICK_AT_SYSTEM_PROMPT = (
    "You are translating a browser automation trace into a Playwright locator. "
    "You will be given: (1) a screenshot the tester saw before clicking, "
    "(2) the (x, y) pixel coordinates they clicked, and (3) the reason they "
    "gave for the click. Your job: return ONE Playwright locator expression "
    "that reliably targets the same element WITHOUT relying on pixel "
    "coordinates. The final test must be layout-independent.\n\n"
    "Selector priority (highest → lowest):\n"
    "  1. page.getByRole('role', { name: 'text' }) — for buttons, links, "
    "textboxes, options with accessible names\n"
    "  2. page.getByLabel('label text') — for labeled form controls\n"
    "  3. page.getByText('visible text', { exact: true }) — for anchored text\n"
    "  4. page.locator('#id') / page.locator('[data-testid=\"x\"]') — stable attributes\n"
    "  5. page.locator('scoped-css-selector') — CSS scoped to a container\n\n"
    "NEVER return:\n"
    "  - page.mouse.click(x, y) or any pixel-based fallback\n"
    "  - .ng-tns-*, .p-element, .p-component, or ui-* prefixes (this codebase "
    "    uses Angular v19 + PrimeNG v19 — the DOM classes those prefixes "
    "    target are unstable)\n"
    "  - auto-generated XPath\n\n"
    "Response format: EXACTLY one line, starting with 'page.', ending in a "
    "single method call (no .click() — the caller will append it). No prose, "
    "no code fence, no explanation. If you truly cannot infer a durable "
    "selector, respond with a single line: UNKNOWN"
)


async def _bedrock_infer_selector(
    screenshot_png: bytes,
    x: int,
    y: int,
    reason: str,
) -> str | None:
    """
    Call Bedrock Sonnet with the screenshot + coords + reason, return the
    locator expression the model produced (without .click() suffix), or
    None if the model responded UNKNOWN / an error occurred.
    """
    try:
        client = _get_bedrock_client()
    except Exception as e:
        logger.warning("codegen: bedrock client unavailable: %s", e)
        return None

    user_text = (
        f"Coordinates clicked: (x={x}, y={y})\n"
        f"Reason given for click: {reason or '(none)'}\n\n"
        "Return the single-line Playwright locator expression, or UNKNOWN."
    )

    messages = [
        {
            "role": "user",
            "content": [
                {"image": {"format": "png", "source": {"bytes": screenshot_png}}},
                {"text": user_text},
            ],
        }
    ]

    try:
        response = client.converse(
            modelId=_model_id(),
            messages=messages,
            system=[{"text": _CLICK_AT_SYSTEM_PROMPT}],
            inferenceConfig={"maxTokens": 200, "temperature": 0.0},
        )
    except Exception as e:
        logger.warning("codegen: bedrock converse failed for click_at at (%d,%d): %s", x, y, e)
        return None

    # Extract the first text block from the assistant response
    out_msg = (response.get("output") or {}).get("message") or {}
    for block in out_msg.get("content") or []:
        text = (block.get("text") or "").strip()
        if not text:
            continue
        # Take the first non-empty line — the prompt asks for exactly one line
        first = text.splitlines()[0].strip()
        if first.upper() == "UNKNOWN":
            return None
        if first.startswith("page."):
            return first
        # Sometimes the model wraps in `page.locator(...)` on a `Locator` line
        # or prepends "Selector: " — clean gently.
        m = re.search(r"(page\.[A-Za-z0-9_.]+\([^\n]*\))\s*$", first)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Transcript reading
# ---------------------------------------------------------------------------


def _iter_indices(transcript_dir: Path) -> list[int]:
    """Sorted list of assistant-turn iteration indices present on disk."""
    out: list[int] = []
    for p in transcript_dir.glob("*_assistant.json"):
        try:
            out.append(int(p.name.split("_", 1)[0]))
        except ValueError:
            continue
    return sorted(out)


def _read_assistant_tool_uses(path: Path) -> list[dict]:
    """
    Load a {iter}_assistant.json and return its toolUse blocks in order.

    Each returned dict has keys ``name`` and ``input``. Non-toolUse blocks
    (text, reasoningContent) are ignored — those don't map to Playwright.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("codegen: cannot read %s: %s", path, e)
        return []
    message = (payload.get("message") or {})
    content = message.get("content") or []
    calls: list[dict] = []
    for block in content:
        tu = block.get("toolUse") if isinstance(block, dict) else None
        if not tu:
            continue
        calls.append({
            "name": tu.get("name") or "",
            "input": tu.get("input") or {},
        })
    return calls


def _parse_numbered_steps(transcript_dir: Path) -> dict[int, str]:
    """
    Extract the ``  [N] step text`` list from ``000_initial_user.json``.

    Returns index → step text. Empty dict if the file is missing or the
    section isn't present.
    """
    initial = transcript_dir / "000_initial_user.json"
    if not initial.exists():
        return {}
    try:
        payload = json.loads(initial.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    text = str(payload.get("text") or "")
    out: dict[int, str] = {}
    for line in text.splitlines():
        m = re.match(r"\s*\[(\d+)\]\s+(.+?)\s*$", line)
        if not m:
            continue
        out[int(m.group(1))] = m.group(2)
    return out


# ---------------------------------------------------------------------------
# Test assembly
# ---------------------------------------------------------------------------


def _test_header(
    ticket_id: str,
    ac_summary: str,
    target_url: str,
    run_id: str,
    generated_at_iso: str,
    user_role: str = "Admin",
    setup_import_path: str = "../../utils/setup",
    playwright_base_url: str = "",
    product_url_constant: str = "",
) -> str:
    """
    Emit the test file header.

    - If ``playwright_base_url`` and ``product_url_constant`` are supplied
      (cross-domain product like vPPO), the header imports the named
      constant and uses it for page.goto() — never a raw URL string.
    - Otherwise falls back to the raw ``target_url``.
    """
    # Navigation URL: prefer the named constant (cross-domain) over the raw URL.
    if playwright_base_url and product_url_constant:
        nav_expression = product_url_constant
        extra_import = f", {product_url_constant}"
    else:
        nav_expression = _ts_string(target_url or "/")
        extra_import = ""

    return (
        f"/**\n"
        f" * {ticket_id}: {ac_summary}\n"
        f" *\n"
        f" * AUTO-GENERATED by vQA Computer-Use loop from run {run_id}\n"
        f" * on {generated_at_iso}.\n"
        f" *\n"
        f" * Review checklist before merging:\n"
        f" *   [ ] Each test.step block runs deterministically on retry\n"
        f" *   [ ] No TODO(codegen) comments remain\n"
        f" *   [ ] Selectors inferred from pixel clicks have been verified\n"
        f" */\n"
        f"\n"
        f"import {{ test, expect{extra_import} }} from '{setup_import_path}';\n"
        f"\n"
        f"test.use({{ user: '{user_role}' }});\n"
        f"\n"
        f"test({_ts_string(f'{ticket_id}: {ac_summary}')}, async ({{ page }}) => {{\n"
        f"  await page.goto({nav_expression}, {{ waitUntil: 'domcontentloaded', timeout: 30_000 }});\n"
        f"\n"
    )


def _test_footer() -> str:
    return "});\n"


def _indent(lines: list[str], levels: int = 2) -> list[str]:
    prefix = "  " * levels
    return [prefix + ln if ln else "" for ln in lines]


async def generate_playwright_test(
    run_id: str,
    ticket_id: str,
    ac_summary: str,
    target_url: str,
    generated_at_iso: str,
    user_role: str = "Admin",
    playwright_base_url: str = "",
    product_url_constant: str = "",
    setup_import_path: str = "../../utils/setup",
) -> str:
    """
    Read run_id's transcript and produce a complete .test.ts file string.

    Parameters
    ----------
    playwright_base_url :
        For cross-domain products (e.g. vPPO), the URL the test should
        navigate to — distinct from target_url which is the SSO gateway.
        When supplied together with product_url_constant, the header will
        import and use the named constant instead of a raw URL string.
    product_url_constant :
        The TypeScript export name to import from setup (e.g. ``VPPO_BASE_URL``).
    setup_import_path :
        Relative import path from the test file to ``playwright/utils/setup``.
        Computed by the caller from the resolved file path.
    """
    tdir = _transcript_dir(run_id)
    if not tdir.exists():
        raise FileNotFoundError(f"No transcript dir for run {run_id!r} at {tdir}")

    numbered_steps = _parse_numbered_steps(tdir)
    click_at_selector_cache: dict[tuple[int, int], str | None] = {}

    body_parts: list[str] = [
        _test_header(
            ticket_id, ac_summary, target_url, run_id, generated_at_iso,
            user_role,
            setup_import_path=setup_import_path,
            playwright_base_url=playwright_base_url,
            product_url_constant=product_url_constant,
        ),
    ]

    # Current test.step block accumulator. When we see mark_step_status
    # (in_progress) we open a block; when we see (passed / failed / skipped)
    # we flush it. Actions that arrive between "no active block" and the
    # first in_progress land in a synthesized "Setup" block so nothing
    # gets silently dropped.
    current_block_lines: list[str] = []
    current_block_label: str | None = None
    open_step_index: int | None = None

    def flush_block():
        nonlocal current_block_lines, current_block_label, open_step_index
        if not current_block_lines:
            current_block_lines = []
            current_block_label = None
            open_step_index = None
            return
        label = current_block_label or "Step"
        body_parts.append(f"  await test.step({_ts_string(label)}, async () => {{\n")
        for ln in _indent(current_block_lines, levels=2):
            body_parts.append(ln + "\n")
        body_parts.append("  });\n\n")
        current_block_lines = []
        current_block_label = None
        open_step_index = None

    for iter_idx in _iter_indices(tdir):
        assistant_path = tdir / f"{iter_idx:03d}_assistant.json"
        screenshot_path = tdir / f"{iter_idx:03d}_screenshot.png"
        for call in _read_assistant_tool_uses(assistant_path):
            name = call["name"]
            args = call["input"] or {}

            if name == "mark_step_status":
                status = str(args.get("status") or "")
                idx = args.get("index")
                note = str(args.get("note") or "").strip()
                if status == "in_progress":
                    # Flush any prior open block first.
                    flush_block()
                    step_text = numbered_steps.get(int(idx) if idx is not None else -1, "")
                    current_block_label = note or step_text or f"Step {idx}"
                    open_step_index = int(idx) if idx is not None else None
                elif status in ("passed", "failed", "skipped"):
                    # A late note can refine the block label if the model
                    # only supplied it on the passed call.
                    if note and not current_block_label:
                        current_block_label = note
                    flush_block()
                continue

            if name in ("done", "request_help"):
                # Terminal / meta — don't emit code, don't affect blocks.
                continue

            if name == "click_at":
                try:
                    x = int(args.get("x", 0))
                    y = int(args.get("y", 0))
                except (TypeError, ValueError):
                    x = y = 0
                reason = str(args.get("reason") or "")
                bucket = (x // _CLICK_AT_BUCKET_PX, y // _CLICK_AT_BUCKET_PX)
                if bucket in click_at_selector_cache:
                    selector = click_at_selector_cache[bucket]
                else:
                    png_bytes: bytes | None = None
                    if screenshot_path.exists():
                        try:
                            png_bytes = screenshot_path.read_bytes()
                        except OSError as e:
                            logger.warning(
                                "codegen: cannot read screenshot %s: %s",
                                screenshot_path, e,
                            )
                    if png_bytes:
                        selector = await _bedrock_infer_selector(png_bytes, x, y, reason)
                    else:
                        selector = None
                    click_at_selector_cache[bucket] = selector

                if selector:
                    current_block_lines.append(f"{selector}.click();  // was click_at({x}, {y})")
                else:
                    # LLM couldn't infer — leave a TODO. Do NOT emit a
                    # pixel click; a broken test that fails loudly is
                    # better than one that passes on this workstation
                    # and breaks in CI.
                    reason_short = reason[:80].replace("*/", "* /")
                    current_block_lines.append(
                        f"// TODO(codegen): replace pixel click at ({x}, {y}) — "
                        f"reason: {reason_short}"
                    )
                    current_block_lines.append(
                        f"await page.mouse.click({x}, {y});"
                    )
                continue

            translator = _DIRECT_TRANSLATORS.get(name)
            if translator is None:
                current_block_lines.append(f"// TODO(codegen): unknown tool {name!r} — args={json.dumps(args)}")
                continue
            try:
                line = translator(args)
            except Exception as e:
                logger.warning("codegen: translator %s failed on %s: %s", name, args, e)
                current_block_lines.append(
                    f"// TODO(codegen): translation of {name!r} failed — {e}"
                )
                continue
            current_block_lines.append(line)

    # Flush any final open block (e.g. run ended before a passed mark).
    flush_block()

    body_parts.append(_test_footer())
    return "".join(body_parts)


# ---------------------------------------------------------------------------
# Filename resolution
# ---------------------------------------------------------------------------


def resolve_test_path(
    playwright_tests_root: Path,
    product: str,
    slug: str,
) -> Path:
    """
    Return the path to write the generated .spec.ts to, auto-suffixing on
    collision (``{slug}-cu.spec.ts`` → ``{slug}-cu-2.spec.ts`` → …).

    Product is used as a subdirectory. If the product folder does not
    exist it will be created by the caller.
    """
    # Guard against empty product BEFORE slugify — slugify returns "unnamed"
    # for empty input (a good filename default), but for a product folder
    # "misc" is more idiomatic.
    product_slug = slugify(product) if product and product.strip() else "misc"
    product_dir = playwright_tests_root / product_slug
    base = f"{slug}-cu"
    candidate = product_dir / f"{base}.test.ts"
    if not candidate.exists():
        return candidate
    for n in range(2, 1000):
        candidate = product_dir / f"{base}-{n}.test.ts"
        if not candidate.exists():
            return candidate
    # Should never realistically happen — 1000 duplicate names.
    raise RuntimeError(
        f"Could not find an available filename for {base!r} in {product_dir}"
    )
