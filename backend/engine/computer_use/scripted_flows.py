"""
Scripted flows for the Computer-Use loop.

Deterministic, product-specific macros that the model can invoke in one tool
call instead of driving the browser field-by-field. This is a hand-authored
Python port of the runbook in `playwright/utils/prf/CreatePrfHelper.ts`
(and its dependencies FormbuilderHelper / Select2v3Helper) — the same
recipe the Playwright test suite uses.

Why this exists: on tickets like QA-359 the CU loop otherwise burns
200+ iterations clicking through every field on the PRF drawer and
gets stuck when a scroll/save round-trip diverges from expectation.
Calling `createPrfHappyPath` here collapses that into ~1 tool call.

Design contract:
  * Every flow returns a `FlowResult` (`ok: bool`, `message: str`,
    optional `data: dict`). Never raises; the runner surfaces the
    message back to the model verbatim.
  * Flows operate on the live Playwright `Page` — same page the CU
    loop is using — so subsequent screenshots reflect the post-flow
    state.
  * Flows do NOT emit `mark_step_status`. The model marks steps
    before/after invoking the flow; the flow is a mechanical macro,
    not a step-tracker.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Awaitable

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class FlowResult:
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def format(self, flow_name: str) -> str:
        """Compact single-line result the runner can put in the tool_result."""
        prefix = "ok" if self.ok else "error"
        line = f"scripted_flow[{flow_name}] {prefix} — {self.message}"
        if self.data:
            keys = ", ".join(f"{k}={v}" for k, v in self.data.items())
            line = f"{line} ({keys})"
        return line


# ---------------------------------------------------------------------------
# Datetime formatting (ports FormbuilderHelper.formatDateTimeForPicker)
# ---------------------------------------------------------------------------


def _format_datetime_for_picker(dt: datetime) -> str:
    """MM-DD-YYYY hh:mm A (12-hour with literal AM/PM)."""
    hour24 = dt.hour
    hour12 = hour24 % 12 or 12
    ampm = "PM" if hour24 >= 12 else "AM"
    return f"{dt.month:02d}-{dt.day:02d}-{dt.year} {hour12:02d}:{dt.minute:02d} {ampm}"


def _safe_start_end_defaults() -> tuple[str, str]:
    """Today + 7d @ 09:00 AM, today + 8d @ 09:00 AM — matches the TS helper."""
    start = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=7)
    end = start + timedelta(days=1)
    return _format_datetime_for_picker(start), _format_datetime_for_picker(end)


# ---------------------------------------------------------------------------
# Select2 v3 primitives (ports Select2v3Helper)
# ---------------------------------------------------------------------------


async def _s2id_for(page: Page, field_name: str) -> str:
    """Build the `s2id_<form-id>_<field>` container id for a formbuilder select2."""
    form_id = await _get_prf_form_id(page)
    cleaned = field_name.lstrip("_")
    return f"s2id_{form_id}_{cleaned}"


async def _open_select2_multi(page: Page, container_id: str) -> None:
    container = page.locator(f"#{container_id}").first
    await container.wait_for(state="visible", timeout=8000)

    ul_input = container.locator("ul.select2-choices input.select2-input").first
    try:
        if await ul_input.is_visible(timeout=1500):
            await ul_input.click()
        else:
            await container.locator("ul.select2-choices").first.click()
    except Exception:
        await container.locator("ul.select2-choices").first.click()

    drop = page.locator(
        "body > div.select2-drop-multi.select2-drop-active, "
        "body > div.select2-drop.select2-drop-active"
    ).first
    await drop.wait_for(state="visible", timeout=5000)


async def _open_select2_single(page: Page, container_id: str) -> None:
    container = page.locator(f"#{container_id}").first
    await container.wait_for(state="visible", timeout=8000)

    choice = container.locator("a.select2-choice").first
    await choice.wait_for(state="visible", timeout=5000)
    await choice.click()

    drop = page.locator("body > div.select2-drop.select2-drop-active").first
    await drop.wait_for(state="visible", timeout=5000)


async def _pick_select2_multi(page: Page, container_id: str, values: list[str]) -> None:
    container = page.locator(f"#{container_id}").first
    for value in values:
        await _open_select2_multi(page, container_id)
        drop = page.locator(
            "body > div.select2-drop-multi.select2-drop-active, "
            "body > div.select2-drop.select2-drop-active"
        ).first

        search = drop.locator("input.select2-input").first
        try:
            if await search.is_visible(timeout=800):
                await search.fill("")
                await search.type(value, delay=20)
                # Local filter debounce; longer than default for prefix-collision
                # disambiguation (e.g. "Corporate Contest" vs "Corporate Content").
                await page.wait_for_timeout(300)
        except Exception:
            pass

        items = drop.locator("li.select2-result-selectable")
        await items.first.wait_for(state="visible", timeout=5000)
        # Prefer exact-label match; fall back to substring.
        exact = items.filter(
            has=page.locator(f'.select2-result-label:text-is("{value}")')
        ).first
        target = exact
        if not await exact.is_visible(timeout=600):
            target = items.filter(has_text=value).first
        await target.wait_for(state="visible", timeout=3000)
        await target.click()

        # Confirm the tag rendered.
        tag = container.locator("ul.select2-choices li.select2-search-choice").filter(
            has_text=value
        ).first
        await tag.wait_for(state="visible", timeout=3000)

        # Cat-change-checker may revoke the pick 300ms later. Verify.
        await page.wait_for_timeout(400)
        if not await tag.is_visible():
            toast = page.locator(".toast-error, .toast-message").last
            msg = (await toast.text_content() or "").strip()
            raise RuntimeError(
                f"select2 multi ({container_id}) pick {value!r} was rejected by "
                f"cat_change_checker. Toast: {msg!r}"
            )


async def _pick_select2_single(page: Page, container_id: str, label_text: str) -> None:
    await _open_select2_single(page, container_id)
    drop = page.locator("body > div.select2-drop.select2-drop-active").first

    search = drop.locator("input.select2-input").first
    try:
        if await search.is_visible(timeout=800):
            await search.fill("")
            await search.type(label_text, delay=20)
            await page.wait_for_timeout(200)
    except Exception:
        pass

    items = drop.locator("li.select2-result-selectable")
    await items.first.wait_for(state="visible", timeout=5000)
    exact = items.filter(
        has=page.locator(f'.select2-result-label:text-is("{label_text}")')
    ).first
    target = exact
    if not await exact.is_visible(timeout=600):
        target = items.filter(has_text=label_text).first
    await target.wait_for(state="visible", timeout=3000)
    await target.click()


async def _pick_select2_ajax(
    page: Page,
    container_id: str,
    query: str,
    *,
    min_chars: int = 3,
    quiet_ms: int = 2000,
) -> None:
    if len(query) < min_chars:
        raise ValueError(
            f"pickSelect2Ajax: query {query!r} shorter than minimumInputLength "
            f"{min_chars} — XHR will not fire."
        )
    await _open_select2_single(page, container_id)
    drop = page.locator("body > div.select2-drop.select2-drop-active").first

    search = drop.locator("input.select2-input").first
    await search.wait_for(state="visible", timeout=3000)
    await search.fill("")
    await search.type(query, delay=20)

    searching = drop.locator("li.select2-searching").first
    try:
        await searching.wait_for(state="attached", timeout=3500)
    except PlaywrightTimeoutError:
        pass
    await page.wait_for_timeout(quiet_ms + 500)
    try:
        await searching.wait_for(state="detached", timeout=15000)
    except PlaywrightTimeoutError:
        pass

    items = drop.locator("li.select2-result-selectable")
    count = await items.count()
    if count == 0:
        raise RuntimeError(
            f"pickSelect2Ajax: no selectable results for {query!r} in #{container_id}"
        )
    target = items.filter(has_text=query).first
    await target.wait_for(state="visible", timeout=3000)
    await target.click()


# ---------------------------------------------------------------------------
# Formbuilder primitives (ports FormbuilderHelper)
# ---------------------------------------------------------------------------


async def _get_prf_form_id(page: Page) -> str:
    form = page.locator('#prf_form_rightview form[id$="_form"]').first
    await form.wait_for(state="visible", timeout=8000)
    form_id = await form.get_attribute("id")
    if not form_id:
        raise RuntimeError("getPrfFormId: form has no id attribute")
    return form_id


async def _fill_text_field(page: Page, field_name: str, value: str) -> None:
    cleaned = field_name.lstrip("_")
    locator = page.locator(
        f'#prf_form_rightview input.field-{cleaned}:visible, '
        f'#prf_form_rightview input[name="_{cleaned}"]:visible, '
        f'#prf_form_rightview input[id$="_{cleaned}"]:visible'
    ).first
    await locator.wait_for(state="visible", timeout=5000)
    await locator.fill(value)
    try:
        await locator.press("Tab")
    except Exception:
        pass


async def _fill_tasp_field(page: Page, field_name: str, content: str) -> None:
    cleaned = field_name.lstrip("_")
    tasp = page.locator(
        f'#prf_form_rightview span.tasp[id$="_{cleaned}_tasp"]:visible, '
        f'#prf_form_rightview span.tasp[name="_{cleaned}"]:visible'
    ).first
    await tasp.wait_for(state="visible", timeout=5000)
    await tasp.click()
    # Select-all + delete for both platforms.
    for combo in ("Control+A", "Meta+A"):
        try:
            await page.keyboard.press(combo)
        except Exception:
            pass
    try:
        await page.keyboard.press("Delete")
    except Exception:
        pass
    await page.keyboard.type(content)
    try:
        await page.keyboard.press("Tab")
    except Exception:
        pass


async def _fill_date_picker(page: Page, field_name: str, value: str) -> None:
    cleaned = field_name.lstrip("_")
    inp = page.locator(
        f'#prf_form_rightview input.datetimepicker[id$="_{cleaned}"]:visible, '
        f'#prf_form_rightview input.datetimepicker[name="_{cleaned}"]:visible'
    ).first
    await inp.wait_for(state="visible", timeout=5000)
    await inp.click()
    for combo in ("Control+A", "Meta+A"):
        try:
            await page.keyboard.press(combo)
        except Exception:
            pass
    try:
        await page.keyboard.press("Delete")
    except Exception:
        pass
    await page.keyboard.type(value, delay=20)
    try:
        await inp.press("Tab")
    except Exception:
        pass
    await page.wait_for_timeout(300)

    error_toast = page.locator(".toast-error, .toast-message.toast-error").last
    try:
        if await error_toast.is_visible(timeout=200):
            msg = ((await error_toast.text_content()) or "").strip()
            if "invalid" in msg.lower() and "date" in msg.lower():
                raise RuntimeError(
                    f"fillPrfDatePicker: {value!r} rejected as Invalid Date on _{cleaned}"
                )
    except PlaywrightTimeoutError:
        pass


async def _wait_for_save_enabled(page: Page, timeout_ms: int = 10_000):
    submit = page.locator(
        "#prf_form_rightview .form-buttons "
        "button[type=submit].prf_submit:not(:disabled):visible"
    ).first
    await submit.wait_for(state="visible", timeout=timeout_ms)
    return submit


# ---------------------------------------------------------------------------
# Flow: createPrfHappyPath
# ---------------------------------------------------------------------------


async def _create_prf_happy_path(page: Page, args: dict[str, Any]) -> FlowResult:
    """
    Open the New-PRF drawer, fill required fields, and save.

    Args (all optional except title):
      title: str                         — PRF title text
      category: str | list[str]          — one or more category labels
      stations: list[str]                — station labels
      sales_assignment: str              — full label including parens
      start_datetime: str                — "MM-DD-YYYY hh:mm A" (defaults to +7d 09:00)
      end_datetime: str                  — "MM-DD-YYYY hh:mm A" (defaults to +8d 09:00)
      description: str                   — Description tasp content
      save_as: "submit" | "draft"        — which save button to click (default "submit")
      extra_text_fields: dict[str, str]  — additional text fields by formbuilder name
    """
    title = str(args.get("title") or "").strip()
    if not title:
        return FlowResult(False, "title is required")

    category_raw = args.get("category") or "Contest"
    if isinstance(category_raw, str):
        categories = [category_raw]
    elif isinstance(category_raw, list):
        categories = [str(c) for c in category_raw if str(c).strip()]
    else:
        categories = ["Contest"]

    stations = args.get("stations") or []
    if isinstance(stations, str):
        stations = [stations]
    stations = [str(s) for s in stations if str(s).strip()]

    sales_assignment = args.get("sales_assignment")
    description = args.get("description")

    default_start, default_end = _safe_start_end_defaults()
    start_dt = str(args.get("start_datetime") or default_start)
    end_dt = str(args.get("end_datetime") or default_end)

    save_as = str(args.get("save_as") or "submit").lower()
    if save_as not in ("submit", "draft"):
        return FlowResult(False, f"save_as must be 'submit' or 'draft', got {save_as!r}")

    extra_text = args.get("extra_text_fields") or {}
    if not isinstance(extra_text, dict):
        extra_text = {}

    # ── Step 1: open drawer ─────────────────────────────────────────────
    new_btn = page.locator("#create_new_prf").first
    try:
        # Fall back to visible-text button if #create_new_prf isn't present.
        if not await new_btn.is_visible(timeout=2000):
            new_btn = page.get_by_text("+ New PRF", exact=False).first
        await new_btn.wait_for(state="visible", timeout=8000)
        await new_btn.click()
    except Exception as e:
        return FlowResult(False, f"could not click New PRF button — {_short(e)}")

    drawer = page.locator("#prf_form_rightview")
    try:
        await drawer.wait_for(state="visible", timeout=8000)
        await drawer.locator('form[id$="_form"]').first.wait_for(
            state="visible", timeout=8000
        )
        await drawer.locator('input[id$="_title"]').first.wait_for(
            state="visible", timeout=8000
        )
    except Exception as e:
        return FlowResult(False, f"PRF drawer did not open — {_short(e)}")

    # ── Step 2: fill Title ──────────────────────────────────────────────
    try:
        title_input = drawer.locator("input.field-title").first
        if not await title_input.is_visible(timeout=500):
            title_input = drawer.locator('input[id$="_title"]').first
        await title_input.fill(title)
        try:
            await title_input.press("Tab")
        except Exception:
            pass
    except Exception as e:
        return FlowResult(False, f"could not fill Title — {_short(e)}")

    # ── Step 3: Category ────────────────────────────────────────────────
    try:
        cat_container = await _s2id_for(page, "category")
        await _pick_select2_multi(page, cat_container, categories)
    except Exception as e:
        return FlowResult(False, f"category pick failed — {_short(e)}")

    # ── Step 4: Stations ────────────────────────────────────────────────
    if stations:
        try:
            st_container = await _s2id_for(page, "stations")
            await _pick_select2_multi(page, st_container, stations)
        except Exception as e:
            return FlowResult(False, f"stations pick failed — {_short(e)}")

    # ── Step 5: Sales Assignment (best-effort — spelling varies) ───────
    if sales_assignment:
        picked = False
        for field in ("sales_person_id", "salesperson_id"):
            try:
                container_id = await _s2id_for(page, field)
                container = page.locator(f"#{container_id}").first
                if await container.is_visible(timeout=1500):
                    await _pick_select2_single(page, container_id, sales_assignment)
                    picked = True
                    break
            except Exception:
                continue
        if not picked:
            logger.info(
                "createPrfHappyPath: sales_assignment=%r — no matching select2 "
                "container (sales_person_id/salesperson_id); leaving unfilled",
                sales_assignment,
            )

    # ── Step 6: Start/End datetimes ─────────────────────────────────────
    try:
        await _fill_date_picker(page, "event_startdatetime", start_dt)
        await _fill_date_picker(page, "event_enddatetime", end_dt)
    except Exception as e:
        return FlowResult(False, f"datetime pickers failed — {_short(e)}")

    # ── Step 6b: Description ────────────────────────────────────────────
    if description:
        try:
            await _fill_tasp_field(page, "description", str(description))
        except Exception as e:
            logger.info("createPrfHappyPath: description skipped — %s", _short(e))

    # ── Step 6c: Extra text fields ──────────────────────────────────────
    for name, val in extra_text.items():
        try:
            await _fill_text_field(page, str(name), str(val))
        except Exception as e:
            logger.info(
                "createPrfHappyPath: extra field %r skipped — %s", name, _short(e)
            )

    # ── Step 7: Save ────────────────────────────────────────────────────
    button_css = (
        "#prf_form_rightview .prf_submit"
        if save_as == "submit"
        else "#prf_form_rightview .btn-is-draft"
    )
    try:
        if save_as == "submit":
            btn = await _wait_for_save_enabled(page)
        else:
            btn = page.locator(button_css).first
            await btn.wait_for(state="visible", timeout=8000)
        await btn.click()
    except Exception as e:
        return FlowResult(False, f"save click ({save_as}) failed — {_short(e)}")

    # Race success vs error toast (present-in-DOM, not just visible).
    # asyncio.wait FIRST_COMPLETED so we don't hang for 10s waiting on the
    # loser once we know the outcome.
    success = page.locator(".toast-success, .toast-message.toast-success").first
    error = page.locator(".toast-error, .toast-message.toast-error").first

    async def _wait(loc, name):
        try:
            await loc.wait_for(state="attached", timeout=10_000)
            return name
        except PlaywrightTimeoutError:
            return None

    winner: str | None = None
    try:
        done, pending = await asyncio.wait(
            {asyncio.create_task(_wait(success, "success")),
             asyncio.create_task(_wait(error, "error"))},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in done:
            r = t.result()
            if r == "success":
                winner = "success"
                break
            if r == "error" and winner is None:
                winner = "error"
        for t in pending:
            t.cancel()
    except Exception:
        winner = None

    if winner == "error":
        msg = ((await error.text_content()) or "").strip()[:400]
        return FlowResult(False, f"save toast: {msg!r}", {"save_as": save_as})
    if winner != "success":
        return FlowResult(
            False,
            "no toast within 10s — record status unknown; check screenshot",
            {"save_as": save_as},
        )

    # Success — read new record id if drawer stayed open.
    record_id = None
    try:
        if not await drawer.is_hidden():
            id_input = drawer.locator('input[id$="_id"]').first
            record_id = (await id_input.input_value()) or None
    except Exception:
        pass

    toast_text = ""
    try:
        toast_text = ((await success.text_content()) or "").strip()[:200]
    except Exception:
        pass

    return FlowResult(
        True,
        f"PRF saved ({save_as}); toast={toast_text!r}",
        {"record_id": record_id or "", "save_as": save_as},
    )


# ---------------------------------------------------------------------------
# Registry + dispatcher
# ---------------------------------------------------------------------------


def _short(e: Exception) -> str:
    return str(e).split("\n")[0][:300]


FlowHandler = Callable[[Page, dict[str, Any]], Awaitable[FlowResult]]

SCRIPTED_FLOWS: dict[str, FlowHandler] = {
    "createPrfHappyPath": _create_prf_happy_path,
}


async def run_scripted_flow(page: Page, name: str, args: dict[str, Any]) -> str:
    """
    Entry point used by the CU tool dispatcher. Returns the single-line
    result the model reads back — always non-empty, never raises.
    """
    handler = SCRIPTED_FLOWS.get(name)
    if not handler:
        available = ", ".join(sorted(SCRIPTED_FLOWS.keys()))
        return (
            f"scripted_flow[{name}] error — unknown flow. "
            f"Available flows: {available}"
        )
    try:
        result = await handler(page, args or {})
    except Exception as e:
        logger.exception("scripted_flow %s raised: %s", name, e)
        return f"scripted_flow[{name}] error — {_short(e)}"
    return result.format(name)
